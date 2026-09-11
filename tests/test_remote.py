"""Remote mode uses fake servers and credentials, never personal accounts."""
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import ssl
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import omaproxy
import quotas


class RemoteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.config = Path(temporary.name)
        override = patch.object(omaproxy, "CONFIG", self.config)
        override.start()
        self.addCleanup(override.stop)
        self.cfg = {"mode": "remote", "base_url": "https://proxy.example.test/prefix",
                    "management_key": "management-secret", "api_key": "client-secret"}

    def save(self, cfg=None):
        omaproxy.private_write(self.config / "connection.json", json.dumps({"mode": "remote", "remote": cfg or self.cfg}))

    def cli(self, command, payload=None):
        output = io.StringIO()
        with patch.object(sys, "argv", ["omaproxy", *command]), \
             patch.object(sys, "stdin", io.StringIO(json.dumps(payload) + "\n")), \
             patch.object(sys, "stdout", output):
            code = omaproxy.main()
        return code, json.loads(output.getvalue())

    def test_remote_setup_needs_no_binary_or_service_and_preserves_local(self):
        local = '{"port": 18317, "api_key": "local-client", "management_key": "local-management"}'
        omaproxy.private_write(self.config / "settings.json", local)
        with patch.object(omaproxy, "request", side_effect=[{"files": []}, {"data": []}]) as request, \
             patch.object(omaproxy, "run", side_effect=AssertionError("No process needed")):
            code, result = self.cli(["connection-save"], self.cfg)
        self.assertEqual(code, 0)
        self.assertTrue(result["connection_changed"])
        self.assertEqual(self.config.joinpath("settings.json").read_text(), local)
        self.assertEqual((self.config / "connection.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(request.call_args_list[0].args, (self.cfg["base_url"] + "/v0/management/auth-files", "management-secret"))
        self.assertEqual(request.call_args_list[1].args, (self.cfg["base_url"] + "/v1/models", "client-secret"))
        self.assertNotIn("secret", json.dumps(result))
        omaproxy.connection_local()
        self.assertEqual(omaproxy.settings()["port"], 18317)

    def test_invalid_urls_never_receive_credentials(self):
        for url in ["http://example.test", "https://user:secret@example.test", "https://example.test?key=x",
                    "https://example.test/#x", "https://example.test:bad", "https://example.test:0",
                    "https://example.test/v1", "https://example.test/v0/management", "https://example.test/a\nb",
                    "file:///tmp/key", "https:///missing", "https://example.test\\evil"]:
            with self.subTest(url=url), patch.object(omaproxy, "request") as request:
                with self.assertRaises(ValueError):
                    omaproxy.connection_save(dict(self.cfg, base_url=url))
                request.assert_not_called()
        for url in ["http://127.0.0.1:18317", "http://[::1]:18317", "https://example.test/prefix/"]:
            self.assertEqual(omaproxy.validate_base_url(url), url.rstrip("/"))

    def test_failed_validation_preserves_active_connection(self):
        self.save()
        before = (self.config / "connection.json").read_text()
        with patch.object(omaproxy, "request", side_effect=urllib.error.HTTPError("", 401, "private-response", {}, None)):
            code, result = self.cli(["connection-save"], dict(self.cfg, base_url="https://other.example.test"))
        self.assertEqual(code, 1)
        self.assertNotIn("private-response", json.dumps(result))
        self.assertEqual((self.config / "connection.json").read_text(), before)

    def test_saved_keys_reused_only_for_same_server(self):
        self.save()
        with patch.object(omaproxy, "request", side_effect=[{"files": []}, {"data": []}]):
            omaproxy.connection_save({"base_url": self.cfg["base_url"]})
        self.assertEqual(omaproxy.settings()["management_key"], "management-secret")
        with patch.object(omaproxy, "request") as request:
            with self.assertRaises(ValueError):
                omaproxy.connection_save({"base_url": "https://different.example.test"})
            request.assert_not_called()

    def test_management_only_connection_and_secret_allowlist(self):
        self.save(dict(self.cfg, api_key=""))
        with patch.object(omaproxy, "request", return_value={"files": [{"name": "fake", "access_token": "private-token"}]}), \
             patch.object(omaproxy, "systemctl", side_effect=AssertionError("Remote mode must not use systemd")):
            result = omaproxy.status()
        self.assertTrue(result["running"])
        self.assertFalse(result["has_api_key"])
        self.assertEqual(result["models"], [])
        for secret in ("private-token", "management-secret", "client-secret"):
            self.assertNotIn(secret, json.dumps(result))

    def test_url_can_be_prefilled_without_sending_unauthenticated_requests(self):
        self.save(dict(self.cfg, management_key="", api_key=""))
        with patch.object(omaproxy, "request") as request:
            result = omaproxy.status()
        self.assertFalse(result["configured"])
        self.assertEqual(result["base_url"], self.cfg["base_url"])
        request.assert_not_called()

    def test_switch_to_unconfigured_local_retains_remote_url_without_installing(self):
        self.save()
        with patch.object(omaproxy, "run", side_effect=AssertionError("No install or service commands")):
            self.assertEqual(self.cli(["connection-local"])[0], 0)
            result = omaproxy.status()
        self.assertFalse(result["configured"])
        self.assertEqual(result["remote_base_url"], self.cfg["base_url"])

    def test_management_auth_failure_stops_automatic_retries_until_save(self):
        self.save()
        error = urllib.error.HTTPError("", 403, "Forbidden", {}, None)
        with patch.object(omaproxy, "request", side_effect=error) as request:
            self.assertFalse(omaproxy.status()["running"])
            self.assertFalse(omaproxy.status()["running"])
            self.assertEqual(request.call_count, 1)
        with patch.object(omaproxy, "request", side_effect=[{"files": []}, {"data": []}]):
            omaproxy.connection_save(self.cfg)
        self.assertFalse((omaproxy.state_dir(self.cfg) / "auth-error.json").exists())

    def test_model_failure_does_not_hide_accounts_or_retry_bad_key(self):
        self.save()
        def request(url, *args, **kwargs):
            if url.endswith("/models"):
                raise urllib.error.HTTPError("", 401, "Unauthorized", {}, None)
            return {"files": [{"name": "fake"}]}
        with patch.object(omaproxy, "request", side_effect=request) as call:
            for _ in range(2):
                result = omaproxy.status()
                self.assertTrue(result["running"])
                self.assertEqual(result["accounts"][0]["name"], "fake")
                self.assertIn("model_error", result)
            self.assertEqual(call.call_count, 3)

    def test_local_actions_rejected_in_remote_mode(self):
        self.save()
        for command in [["setup"], ["start"], ["stop"], ["restart"], ["autostart", "on"],
                        ["config"], ["logs"], ["logs-view"], ["login", "codex"], ["auth-start", "codex"]]:
            with self.subTest(command=command), patch.object(omaproxy, "run", side_effect=AssertionError("No local process")):
                code, result = self.cli(command)
                self.assertEqual(code, 1)
                self.assertIn("local proxy", result["error"])

    def test_remote_dashboard_and_clipboard_use_selected_endpoint(self):
        self.save()
        with patch.object(omaproxy, "run") as run:
            self.assertEqual(self.cli(["dashboard"])[0], 0)
            self.assertEqual(run.call_args.args[0], ["xdg-open", self.cfg["base_url"] + "/management.html"])
        with patch.object(omaproxy.subprocess, "run") as run:
            self.assertEqual(self.cli(["copy", "endpoint"])[0], 0)
            self.assertEqual(run.call_args.kwargs["input"], self.cfg["base_url"] + "/v1")

    def test_malformed_responses_and_transport_errors_are_sanitized(self):
        self.save()
        for response in [[], {}, {"files": "bad"}, {"files": [None]}, {"files": [{}]}]:
            with patch.object(omaproxy, "request", return_value=response):
                self.assertFalse(omaproxy.status()["running"])
        for error in [TimeoutError("private-network-detail"), ssl.SSLCertVerificationError("private-certificate-detail"),
                      urllib.error.URLError("private-network-detail")]:
            with patch.object(omaproxy, "request", side_effect=error):
                result = omaproxy.status()
                self.assertFalse(result["running"])
                self.assertNotIn("private-", json.dumps(result))

    def test_inflight_quota_refresh_keeps_original_server_and_cache(self):
        self.save()
        first = dict(self.cfg)
        second = dict(first, base_url="https://second.example.test")
        calls = []
        def api(route, *args, cfg=None, **kwargs):
            calls.append(cfg["base_url"])
            return {"files": [{"name": "fake", "provider": "codex", "auth_index": "same-id"}]}
        def fetch(account, call_api):
            self.save(second)
            call_api("api-call", "POST", {})
            return {"windows": [{"remaining_percent": 75}]}
        with patch.object(omaproxy, "api", side_effect=api), patch.object(quotas, "fetch", side_effect=fetch):
            omaproxy.quota_snapshot()
        self.assertEqual(calls, [first["base_url"], first["base_url"]])
        self.assertTrue((omaproxy.state_dir(first) / "quotas.json").exists())
        self.assertFalse((omaproxy.state_dir(second) / "quotas.json").exists())
        self.assertNotEqual(omaproxy.connection_id(first), omaproxy.connection_id(dict(first, management_key="new-key")))

    def test_multistep_action_keeps_connection_snapshot(self):
        self.save()
        calls = []
        def request(url, *args, **kwargs):
            calls.append(url)
            self.save(dict(self.cfg, base_url="https://second.example.test"))
            return {"openai-compatibility": []}
        with patch.object(omaproxy, "request", side_effect=request):
            code, _ = self.cli(["custom-add"], {"name": "fake", "url": "https://upstream.example.test/v1", "key": "fake", "models": "fake"})
        self.assertEqual(code, 0)
        self.assertEqual(calls, [self.cfg["base_url"] + "/v0/management/openai-compatibility"] * 2)

    def test_http_server_path_prefix_credentials_and_redirect_refusal(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                requests.append((self.path, self.headers.get("Authorization")))
                if self.path == "/prefix/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/credential-leak")
                    self.end_headers()
                    return
                data = {"files": [{"name": "fake", "access_token": "hidden-token"}]} if self.path.endswith("auth-files") else {"data": [{"id": "fake-model"}]}
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                cfg = dict(self.cfg, base_url=f"http://127.0.0.1:{server.server_port}/prefix")
                omaproxy.connection_save(cfg)
                result = omaproxy.status()
                self.assertTrue(result["running"])
                self.assertEqual(result["models"], ["fake-model"])
                self.assertNotIn("hidden-token", json.dumps(result))
                with self.assertRaises(urllib.error.HTTPError):
                    omaproxy.request(cfg["base_url"] + "/redirect", "management-secret")
                self.assertNotIn("/credential-leak", [path for path, _ in requests])
                self.assertEqual(requests[:2], [("/prefix/v0/management/auth-files", "Bearer management-secret"),
                                               ("/prefix/v1/models", "Bearer client-secret")])
            finally:
                server.shutdown()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
