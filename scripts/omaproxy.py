#!/usr/bin/env python3
"""OmaProxy's local bridge. Python standard library only; JSON stdout for QML."""
import argparse
import concurrent.futures
import fcntl
import hashlib
import gzip
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "omaproxy"
DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "omaproxy"
UNIT = "omaproxy.service"
REPO = "router-for-me/CLIProxyAPI"
VERSION = "v7.2.154"
# Trust anchors reviewed with this plugin snapshot; never derive these at install
# time from release metadata. A backend update must review and change these pins.
ARCHIVE_SHA256 = {
    "amd64": "2a2256ceff048d5fa813aa54e8daa43e870b40e698d5cd21efad46e25aa5a1f9",
    "aarch64": "3a0cd18d64e3b9990ca72136dbb1da97eedddade00ee6768e8b49fab1de6925e",
}
CHECKSUM_MAX_BYTES = 64 * 1024
ARCHIVE_MAX_BYTES = 32 * 1024 * 1024
BINARY_MAX_BYTES = 64 * 1024 * 1024
METADATA_MAX_BYTES = 128 * 1024
EXPANDED_ARCHIVE_MAX_BYTES = 66 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 64 * 1024
RELEASE_MEMBERS = {"cli-proxy-api", "LICENSE", "README.md", "README_CN.md", "config.example.yaml"}
PROVIDERS = [
    ("claude", "Claude", "claude-login"),
    ("codex", "Codex", "codex-login"),
    ("gemini-cli", "Gemini", "login"),
    ("antigravity", "Antigravity", "antigravity-login"),
    ("kimi", "Kimi", "kimi-login"),
    ("qwen", "Qwen", "qwen-login"),
    ("github-copilot", "GitHub Copilot", "github-copilot-login"),
    ("xai", "xAI", "xai-login"),
]


def run(args, check=True, **kwargs):
    return subprocess.run(args, check=check, text=True, capture_output=kwargs.pop("capture_output", True),
                          timeout=kwargs.pop("timeout", 20), **kwargs)


def private_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def settings():
    path = CONFIG / "settings.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Management and client credentials must stay at the selected endpoint.
        return None


def request(url, key=None, method="GET", body=None, timeout=4):
    headers = {"Accept": "application/json", "User-Agent": "OmaProxy/0.1"}
    if key:
        headers["Authorization"] = "Bearer " + key
    data = None if body is None else json.dumps(body).encode()
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    # Local control traffic must never leave via HTTP_PROXY/HTTPS_PROXY.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(req, timeout=timeout) as response:
        return json.load(response)


def api(route, method="GET", body=None, timeout=4):
    cfg = settings()
    if not cfg:
        raise ValueError("Set up the proxy first.")
    return request(f'http://127.0.0.1:{cfg["port"]}/v0/management/{route}',
                   cfg["management_key"], method, body, timeout=timeout)


def systemctl(*args, check=True):
    return run(["systemctl", "--user", *args, UNIT], check=check)


def status():
    cfg = settings()
    result = {"configured": bool(cfg), "running": False, "accounts": [],
              "models": [], "providers": [], "autostart": False,
              "endpoint": "", "service": "not installed", "error": ""}
    if not cfg:
        return result
    result.update(endpoint=f'http://127.0.0.1:{cfg["port"]}/v1',
                  version=cfg.get("version", "custom"),
                  providers=cfg.get("providers", []))
    state = systemctl("is-active", check=False).stdout.strip()
    result["service"] = state or "unknown"
    result["autostart"] = systemctl("is-enabled", check=False).stdout.strip() == "enabled"
    if state != "active":
        result["quotas"] = read_json(CONFIG / "quotas.json", {"accounts": []})
        if state == "failed":
            result["error"] = "Proxy failed to start. Open Logs for details."
        return result
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            auth = pool.submit(api, "auth-files")
            models = pool.submit(request, result["endpoint"] + "/models", cfg["api_key"])
            files = auth.result().get("files", [])
            # Explicit allowlist: never pass tokens, API keys, or raw auth files to QML.
            result["accounts"] = [{k: row.get(k) for k in
                ("name", "auth_index", "provider", "type", "email", "label", "disabled", "status", "success", "failed")}
                for row in files]
            for account, row in zip(result["accounts"], files):
                token_info = row.get("id_token")
                plan = row.get("plan_type") or (token_info.get("plan_type") if isinstance(token_info, dict) else None)
                account["plan"] = plan if isinstance(plan, str) else ""
            result["models"] = sorted({str(row["id"]) for row in models.result().get("data", [])})
        result["running"] = True
    except (OSError, ValueError, urllib.error.URLError):
        result["error"] = "Service is active but its API is unavailable. Check Logs and configuration."
        result["quotas"] = read_json(CONFIG / "quotas.json", {"accounts": []})
    return result


def download(url, max_bytes):
    req = urllib.request.Request(url, headers={"User-Agent": "OmaProxy/0.1"})
    with urllib.request.urlopen(req, timeout=90) as response:
        declared = response.headers.get("Content-Length")
        if declared is not None:
            try:
                length = int(declared)
            except ValueError:
                raise ValueError("Invalid download length; installation stopped.") from None
            if length < 0 or length > max_bytes:
                raise ValueError("Download exceeds size limit; installation stopped.")
        result = bytearray()
        while True:
            chunk = response.read(min(DOWNLOAD_CHUNK_BYTES, max_bytes - len(result) + 1))
            if not chunk:
                break
            if len(result) + len(chunk) > max_bytes:
                raise ValueError("Download exceeds size limit; installation stopped.")
            result.extend(chunk)
        if declared is not None and len(result) != length:
            raise ValueError("Download length mismatch; installation stopped.")
        return bytes(result)


def extract_binary(archive_path, binary_path):
    # Only the exact reviewed flat, regular-file layout is accepted. Never use
    # extract()/extractall(), basename matching, links, or archive-owned paths.
    # Bound total inflation *before* tarfile parses extension headers or sizes.
    with tempfile.TemporaryFile(dir=binary_path.parent) as expanded:
        with gzip.open(archive_path, "rb") as compressed:
            total = 0
            while True:
                chunk = compressed.read(min(DOWNLOAD_CHUNK_BYTES, EXPANDED_ARCHIVE_MAX_BYTES - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > EXPANDED_ARCHIVE_MAX_BYTES:
                    raise ValueError("Expanded archive exceeds size limit; installation stopped.")
                expanded.write(chunk)
        expanded.seek(0)
        _extract_reviewed_tar(expanded, binary_path)


def _extract_reviewed_tar(expanded, binary_path):
    # Inspect raw headers before tarfile can consume GNU/PAX extension records.
    # TarInfo.frombuf only decodes one header and checks its checksum; it never
    # reads an extension payload. The accepted format is five flat regular files.
    seen = set()
    candidate = None
    while True:
        header = expanded.read(512)
        if len(header) != 512:
            raise ValueError("Truncated release archive; installation stopped.")
        if header == bytes(512):
            if expanded.read(512) != bytes(512):
                raise ValueError("Invalid archive terminator; installation stopped.")
            while chunk := expanded.read(DOWNLOAD_CHUNK_BYTES):
                if any(chunk):
                    raise ValueError("Unexpected trailing archive data; installation stopped.")
            break
        member = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
        if (member.name not in RELEASE_MEMBERS or member.name in seen
                or member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE)
                or header[:100].rstrip(b"\0") != member.name.encode("ascii")
                or header[345:500].strip(b"\0")):
            raise ValueError("Unexpected archive member name or type; installation stopped.")
        seen.add(member.name)
        ceiling = BINARY_MAX_BYTES if member.name == "cli-proxy-api" else METADATA_MAX_BYTES
        if not 0 < member.size <= ceiling:
            raise ValueError("Archive member exceeds size limit; installation stopped.")
        if member.name == "cli-proxy-api":
            candidate = (expanded.tell(), member.size)
        expanded.seek(member.size, 1)
        padding_size = (-member.size) % 512
        if expanded.read(padding_size) != bytes(padding_size):
            raise ValueError("Invalid archive member padding; installation stopped.")
    if seen != RELEASE_MEMBERS or candidate is None:
        raise ValueError("Release archive is missing expected files; installation stopped.")
    offset, declared = candidate
    expanded.seek(offset)
    with binary_path.open("wb") as dest:
        total = 0
        while total < declared:
            chunk = expanded.read(min(DOWNLOAD_CHUNK_BYTES, declared - total))
            if not chunk:
                raise ValueError("Extracted executable length mismatch; installation stopped.")
            total += len(chunk)
            if total > BINARY_MAX_BYTES or total > declared:
                raise ValueError("Extracted executable exceeds size limit; installation stopped.")
            dest.write(chunk)
        if total != declared:
            raise ValueError("Extracted executable length mismatch; installation stopped.")
    binary_path.chmod(0o700)


def install_binary():
    arch = {"x86_64": "amd64", "aarch64": "aarch64"}.get(platform.machine())
    if platform.system() != "Linux" or arch not in ARCHIVE_SHA256:
        raise ValueError("Automatic installation supports Linux x86_64 and aarch64.")
    filename = f'CLIProxyAPI_{VERSION.lstrip("v")}_linux_{arch}.tar.gz'
    base = f"https://github.com/{REPO}/releases/download/{VERSION}/"
    expected = ARCHIVE_SHA256[arch]
    print(f"Downloading CLIProxyAPI {VERSION} ({arch}) and verifying pinned SHA-256…", file=sys.stderr)
    # The adjacent checksum is only a consistency check, never the trust anchor.
    checksums = download(base + "checksums.txt", CHECKSUM_MAX_BYTES).decode("ascii")
    reported = [line.split()[0] for line in checksums.splitlines()
                if len(line.split()) == 2 and line.split()[1].lstrip("*") == filename]
    if reported != [expected]:
        raise ValueError("Release checksum does not match pinned digest; installation stopped.")
    archive = download(base + filename, ARCHIVE_MAX_BYTES)
    if hashlib.sha256(archive).hexdigest() != expected:
        raise ValueError("Release checksum mismatch; installation stopped.")
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir=DATA) as temporary:
        path = Path(temporary) / "release.tar.gz"
        path.write_bytes(archive)
        binary = Path(temporary) / "cli-proxy-api"
        extract_binary(path, binary)
        os.replace(binary, DATA / "cli-proxy-api")
    return str(DATA / "cli-proxy-api")


def unit_quote(value):
    # systemd uses its own quoting, specifiers, and dollar expansion, not shell quoting.
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"'


def setup(binary=None, port=8317):
    if not 1024 <= port <= 65535:
        raise ValueError("Port must be between 1024 and 65535.")
    cfg = settings()
    if binary:
        binary = str(Path(binary).expanduser().resolve(strict=True))
        version = "custom"
    else:
        binary = install_binary()
        version = VERSION
    help_result = run([binary, "--help"], check=False)
    help_text = help_result.stdout + help_result.stderr
    supported = set(re.findall(r"^\s+--?([a-z][a-z-]+)(?:\s|$)", help_text, re.M))
    providers = [{"id": ident, "name": name, "flag": flag, "available": flag in supported}
                 for ident, name, flag in PROVIDERS]
    if not cfg:
        cfg = {"port": port, "api_key": "oma-" + secrets.token_urlsafe(32),
               "management_key": secrets.token_urlsafe(40)}
        auth_dir = CONFIG / "auth"
        auth_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        server_config = {"host": "127.0.0.1", "port": port, "auth-dir": str(auth_dir),
            "api-keys": [cfg["api_key"]], "remote-management": {
                "allow-remote": False, "secret-key": cfg["management_key"],
                "disable-auto-update-panel": True},
            "routing": {"strategy": "round-robin"}, "request-retry": 3,
            "quota-exceeded": {"switch-project": True, "switch-preview-model": True},
            "usage-statistics-enabled": True, "logging-to-file": False}
        # JSON is valid YAML; upstream may rewrite this file as YAML later.
        private_write(CONFIG / "config.yaml", json.dumps(server_config, indent=2) + "\n")
    cfg.update(binary=binary, version=version, providers=providers)
    private_write(CONFIG / "settings.json", json.dumps(cfg, indent=2) + "\n")
    unit_dir = CONFIG.parent / "systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit = "\n".join([
        "[Unit]", "Description=OmaProxy local AI proxy", "After=network-online.target", "",
        "[Service]", "Type=simple",
        f"ExecStart={unit_quote(binary)} --config {unit_quote(CONFIG / 'config.yaml')}",
        f"WorkingDirectory={unit_quote(CONFIG)}",
        "Restart=on-failure", "RestartSec=3", "UMask=0077", "NoNewPrivileges=true", "",
        "[Install]", "WantedBy=default.target", ""])
    private_write(unit_dir / UNIT, unit)
    run(["systemctl", "--user", "daemon-reload"])
    return {"message": "Proxy installed. Start it from the OmaProxy bar popup."}


def login(provider):
    cfg = settings()
    selected = next((p for p in cfg["providers"] if p["id"] == provider and p["available"]), None)
    if not selected:
        raise ValueError("This provider is not supported by the installed backend.")
    # Native upstream login handles browser callbacks, device codes, and terminal prompts.
    # Its interactive output never enters the shell process or JSON bridge.
    result = subprocess.run([cfg["binary"], "--config", str(CONFIG / "config.yaml"),
                             "-" + selected["flag"]], check=False)
    if result.returncode:
        raise ValueError("Provider login did not complete. See the terminal output above.")
    return {"message": "Login finished. OmaProxy will refresh your accounts automatically."}


def copy_value(kind):
    cfg = settings()
    values = {"endpoint": f'http://127.0.0.1:{cfg["port"]}/v1',
              "api-key": cfg["api_key"], "management-key": cfg["management_key"]}
    # wl-copy forks a clipboard owner which can outlive this command. Captured
    # output pipes stay open in that child, making communicate() wait until its
    # timeout even though the copy succeeded. Neither output stream is needed.
    subprocess.run(["wl-copy", "--type", "text/plain"], input=values[kind],
                   text=True, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=5)
    return {"message": "Copied to clipboard."}


def read_json(path, fallback):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return fallback


def quota_snapshot(force=False):
    import quotas
    path = CONFIG / "quotas.json"
    cached = read_json(path, {"accounts": []})
    lock_path = CONFIG / "quotas.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"quotas": cached, "message": "Quota refresh already in progress."}
        files = api("auth-files").get("files", [])
        old = {a.get("auth_index") or a["name"]: a for a in cached.get("accounts", [])}
        def refresh_account(account):
            key = account.get("auth_index") or account["name"]
            previous = old.get(key, {})
            identity = {k: account.get(k) for k in ("name", "auth_index", "provider", "email", "label", "disabled", "status")}
            if not force and time.time() - previous.get("checked_at", 0) < 60:
                return dict(previous, **identity)
            try:
                data = quotas.fetch(account, api)
            except (OSError, ValueError, urllib.error.URLError, TypeError, AttributeError, KeyError):
                data = {"windows": [], "error": "Quota check could not reach the provider. Try again shortly."}
            now = time.time()
            if data.get("error") and previous.get("windows"):
                data["windows"] = previous["windows"]
                data["plan"] = previous.get("plan", "")
                data["updated_at"] = previous.get("updated_at", 0)
                data["stale"] = True
            else:
                data["updated_at"] = now if not data.get("error") else 0
                data["stale"] = bool(data.get("error"))
            return dict(data, **identity, checked_at=now)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            accounts = list(pool.map(refresh_account, files))
        result = {"accounts": accounts, "checked_at": time.time()}
        private_write(path, json.dumps(result) + "\n")
        return {"quotas": result}


AUTH_ROUTES = {"claude": "anthropic", "codex": "codex", "antigravity": "antigravity",
               "kimi": "kimi", "xai": "xai", "gemini-cli": "gemini", "qwen": "qwen", "github-copilot": "github-copilot"}


def auth_action(action, provider=None, payload=None):
    # Each bar instance has its own poller. Serialize read/modify/write so a
    # late poll cannot resurrect a cancelled session or replace a newer login.
    CONFIG.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (CONFIG / "oauth-session.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _auth_action(action, provider, payload)


def _auth_action(action, provider=None, payload=None):
    path = CONFIG / "oauth-session.json"
    session = read_json(path, {})
    if action == "auth-start":
        if session.get("state") and session.get("status") == "wait":
            raise ValueError("Finish or cancel the current sign-in first.")
        route = AUTH_ROUTES[provider]
        response = api(route + "-auth-url?is_webui=true", timeout=30)
        url = response.get("url", "")
        if urllib.parse.urlsplit(url).scheme != "https":
            raise ValueError("The backend did not return a secure sign-in URL.")
        if not response.get("state"):
            raise ValueError("The backend did not return a sign-in session.")
        session = {"provider": provider, "route": route, "state": response["state"], "url": url,
                   "user_code": response.get("user_code", ""), "status": "wait", "started_at": time.time()}
        private_write(path, json.dumps(session))
        try:
            run(["xdg-open", url], capture_output=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            session["error"] = "Could not open the browser. Use Open sign-in page to retry."
    elif action == "auth-open":
        if not session.get("url"):
            raise ValueError("Start a sign-in first.")
        run(["xdg-open", session["url"]], capture_output=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif session.get("state"):
        if action == "auth-cancel":
            api("oauth-session?" + urllib.parse.urlencode({"state": session["state"]}), "DELETE")
            session = {}
        elif action == "auth-callback":
            url = str((payload or {}).get("url", "")).strip()
            if not url:
                raise ValueError("Paste the callback URL from your browser.")
            parts = urllib.parse.urlsplit(url)
            states = urllib.parse.parse_qs(parts.query).get("state", [])
            if session["state"] not in states:
                raise ValueError("This callback belongs to another sign-in. Use the URL from the current sign-in page.")
            api("oauth-callback", "POST", {"provider": session["route"], "redirect_url": url})
        elif action == "auth-status" and session.get("status") == "wait":
            response = api("get-auth-status?" + urllib.parse.urlencode({"state": session["state"]}))
            session["status"] = response.get("status", "error")
            # Do not forward raw provider error text, which may contain callback details.
            session["error"] = "Sign-in failed or expired. Cancel and try again." if session["status"] == "error" else ""
        private_write(path, json.dumps(session))
    return {"auth": {k: session.get(k, "") for k in ("provider", "user_code", "status", "error")}}


def logs_snapshot():
    output = run(["journalctl", "--user", "-u", UNIT, "-n", "70", "--no-pager", "-o", "cat"]).stdout
    cfg = settings()
    for key in ("api_key", "management_key"):
        output = output.replace(cfg[key], "[redacted]")
    # Redact auth URLs, bearer values, and token-like fields before entering QML.
    output = re.sub(r'https?://\S*(?:oauth|authorize|callback)\S*', "[sign-in URL]", output, flags=re.I)
    output = re.sub(r'(?i)(Bearer\s+)[^\s"\']+', r'\1[redacted]', output)
    output = re.sub(r'(?i)((?:access_token|refresh_token|id_token|api_key|api-key|secret-key)["\s:=]+)[^\s,"\']+', r'\1[redacted]', output)
    return {"logs": output[-18000:]}


def custom_provider(payload):
    CONFIG.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (CONFIG / "providers.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _custom_provider(payload)


def _custom_provider(payload):
    name = str(payload.get("name", "")).strip()
    url = str(payload.get("url", "")).strip().rstrip("/")
    key = str(payload.get("key", "")).strip()
    models = [x.strip() for x in str(payload.get("models", "")).split(",") if x.strip()]
    parsed = urllib.parse.urlsplit(url)
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", name):
        raise ValueError("Use a provider name with letters, numbers, underscores, or hyphens.")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")):
        raise ValueError("Use an HTTPS endpoint, or an HTTP endpoint on localhost.")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Enter a base URL without credentials, query parameters, or fragments.")
    if not key or not models:
        raise ValueError("Enter an API key and at least one model ID.")
    response = api("openai-compatibility")
    entries = response.get("openai-compatibility", [])
    if any(item.get("name") == name for item in entries):
        raise ValueError("That provider already exists. Choose a different name.")
    entries.append({"name": name, "base-url": url, "api-key-entries": [{"api-key": key}],
                    "models": [{"name": model, "alias": model} for model in models]})
    api("openai-compatibility", "PUT", entries)
    return {"message": "API provider added. Its models are now available."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interactive", action="store_true", help="Keep terminal output visible after completion")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("setup", help="Install the pinned backend and user service")
    p.add_argument("--binary", help="Use a local CLIProxyAPI or Plus executable")
    p.add_argument("--port", type=int, default=8317)
    for name in ("status", "start", "stop", "restart", "dashboard", "logs", "config", "logs-view",
                 "auth-status", "auth-cancel", "auth-open", "auth-callback", "custom-add", "preferences"):
        sub.add_parser(name)
    p = sub.add_parser("quotas")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("auth-start")
    p.add_argument("provider", choices=list(AUTH_ROUTES))
    p = sub.add_parser("routing")
    p.add_argument("strategy", choices=["round-robin", "fill-first"])
    p = sub.add_parser("autostart")
    p.add_argument("value", choices=["on", "off"])
    p = sub.add_parser("login")
    p.add_argument("provider", choices=[p[0] for p in PROVIDERS])
    p = sub.add_parser("account")
    p.add_argument("name")
    p.add_argument("value", choices=["enable", "disable"])
    p.add_argument("--auth-index", default="")
    p = sub.add_parser("copy")
    p.add_argument("kind", choices=["endpoint", "api-key", "management-key"])
    args = parser.parse_args()
    try:
        if args.action == "setup":
            result = setup(args.binary, args.port)
        elif args.action == "status":
            result = status()
        elif not settings():
            raise ValueError("Set up the proxy first.")
        elif args.action == "quotas":
            result = quota_snapshot(args.force)
        elif args.action.startswith("auth-"):
            payload = json.loads(sys.stdin.readline()) if args.action == "auth-callback" else None
            result = auth_action(args.action, getattr(args, "provider", None), payload)
        elif args.action == "custom-add":
            result = custom_provider(json.loads(sys.stdin.readline()))
        elif args.action == "logs-view":
            result = logs_snapshot()
        elif args.action == "preferences":
            result = {"preferences": {"routing": api("routing/strategy").get("strategy", "")}}
        elif args.action == "routing":
            api("routing/strategy", "PUT", {"value": args.strategy})
            result = {"message": "Routing strategy updated.", "preferences": {"routing": args.strategy}}
        elif args.action in ("start", "stop", "restart"):
            systemctl(args.action)
            result = {"message": f"Proxy {args.action} requested."}
        elif args.action == "autostart":
            systemctl("enable" if args.value == "on" else "disable")
            result = {"message": "Launch at login " + ("enabled." if args.value == "on" else "disabled.")}
        elif args.action == "login":
            result = login(args.provider)
        elif args.action == "account":
            payload = {"name": args.name, "disabled": args.value == "disable"}
            if args.auth_index:
                payload["auth_index"] = args.auth_index
            api("auth-files/status", "PATCH", payload)
            result = {"message": "Account updated."}
        elif args.action == "copy":
            result = copy_value(args.kind)
        elif args.action == "dashboard":
            run(["xdg-open", f'http://127.0.0.1:{settings()["port"]}/management.html'])
            result = {"message": "Management panel opened. Use Copy management key to sign in."}
        elif args.action == "config":
            run(["xdg-open", str(CONFIG / "config.yaml")])
            result = {"message": "Proxy configuration opened."}
        else:
            subprocess.run(["journalctl", "--user", "-u", UNIT, "-n", "100", "-f"], check=False)
            return
        print(json.dumps(result))
    except (ValueError, OSError, subprocess.SubprocessError, urllib.error.URLError, tarfile.TarError, EOFError) as exc:
        # HTTP bodies and command output can contain credentials; do not echo them.
        if isinstance(exc, (tarfile.TarError, EOFError)):
            message = "Invalid release archive; installation stopped."
        elif isinstance(exc, urllib.error.HTTPError):
            message = f"Proxy API returned HTTP {exc.code}. Check the backend version and configuration."
        elif isinstance(exc, subprocess.TimeoutExpired):
            message = "Command timed out. Try again or check Logs for details."
        elif isinstance(exc, subprocess.CalledProcessError):
            message = "Command failed. Check Logs for details."
        else:
            message = str(exc)
        print(json.dumps({"error": message}))
        return 1
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        code = 130
    if "--interactive" in sys.argv and sys.stdin.isatty():
        try:
            input("\nPress Enter to close…")
        except (EOFError, KeyboardInterrupt):
            pass
    sys.exit(code)
