import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

spec = importlib.util.spec_from_file_location("bridge", Path(__file__).parents[1] / "scripts/omaproxy.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / "config/omaproxy"
        self.config_patch = patch.object(bridge, "CONFIG", self.config)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)

    def configure(self):
        value = {"port": 18317, "management_key": "management-secret", "api_key": "client-secret",
                 "providers": [], "version": "test", "binary": "/fake/backend"}
        bridge.private_write(self.config / "settings.json", json.dumps(value))
        return value

    def test_first_run_does_not_create_files(self):
        self.assertFalse(bridge.status()["configured"])
        self.assertFalse(self.config.exists())

    def test_private_atomic_write(self):
        target = self.config / "settings.json"
        bridge.private_write(target, "first")
        bridge.private_write(target, "second")
        self.assertEqual(target.read_text(), "second")
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.config.iterdir()), [target])

    def test_status_filters_secrets_and_deduplicates_models(self):
        self.configure()
        def ctl(action, **kwargs):
            return subprocess.CompletedProcess([], 0, "active\n" if action == "is-active" else "enabled\n", "")
        with patch.object(bridge, "systemctl", side_effect=ctl), \
             patch.object(bridge, "api", return_value={"files": [{"name": "account.json", "email": "test@example.com",
                 "provider": "codex", "access_token": "never-expose", "metadata": {"secret": "hidden"}}]}), \
             patch.object(bridge, "request", return_value={"data": [{"id": "b"}, {"id": "a"}, {"id": "b"}]}):
            result = bridge.status()
        self.assertTrue(result["running"])
        self.assertTrue(result["autostart"])
        self.assertEqual(result["models"], ["a", "b"])
        output = json.dumps(result)
        for secret in ("never-expose", "metadata", "management-secret", "client-secret"):
            self.assertNotIn(secret, output)

    def test_active_service_with_unreachable_api_is_not_healthy(self):
        self.configure()
        with patch.object(bridge, "systemctl", return_value=subprocess.CompletedProcess([], 0, "active\n", "")), \
             patch.object(bridge, "api", side_effect=urllib.error.URLError("offline")), \
             patch.object(bridge, "request", return_value={"data": []}):
            result = bridge.status()
        self.assertFalse(result["running"])
        self.assertIn("unavailable", result["error"])

    def test_stopped_service_does_not_probe_another_server(self):
        self.configure()
        with patch.object(bridge, "systemctl", return_value=subprocess.CompletedProcess([], 3, "inactive\n", "")), \
             patch.object(bridge, "api") as api:
            self.assertFalse(bridge.status()["running"])
            api.assert_not_called()

    def test_stopped_status_restores_persisted_quota_readings(self):
        self.configure()
        cached = {"accounts": [{"name": "example", "windows": [{"remaining_percent": 80}]}]}
        bridge.private_write(self.config / "quotas.json", json.dumps(cached))
        with patch.object(bridge, "systemctl", return_value=subprocess.CompletedProcess([], 3, "inactive\n", "")):
            result = bridge.status()
        self.assertFalse(result["running"])
        self.assertEqual(result["quotas"], cached)

    def test_setup_preserves_configuration_and_detects_exact_flags(self):
        cfg = self.configure()
        original = "# hand edited\nport: 18317\n"
        bridge.private_write(self.config / "config.yaml", original)
        executable = Path(self.temp.name) / "backend"
        executable.touch()
        with patch.object(bridge, "run", return_value=subprocess.CompletedProcess([], 0, "", "  -codex-login\n  -qwen-login\n")):
            bridge.setup(str(executable), 8317)
        after = bridge.settings()
        self.assertEqual(after["api_key"], cfg["api_key"])
        self.assertEqual(after["port"], 18317)
        self.assertEqual((self.config / "config.yaml").read_text(), original)
        available = {p["id"] for p in after["providers"] if p["available"]}
        self.assertEqual(available, {"codex", "qwen"})

    def test_setup_rejects_privileged_port_before_download(self):
        with patch.object(bridge, "install_binary") as download:
            with self.assertRaises(ValueError):
                bridge.setup(port=80)
            download.assert_not_called()

    def test_checksum_mismatch_does_not_install(self):
        sums = (bridge.ARCHIVE_SHA256["amd64"] + "  CLIProxyAPI_7.2.154_linux_amd64.tar.gz\n").encode()
        with patch.object(bridge.platform, "machine", return_value="x86_64"), \
             patch.object(bridge, "download", side_effect=[sums, b"wrong archive"]):
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                bridge.install_binary()

    def test_login_rejects_unavailable_provider(self):
        self.configure()
        with patch.object(bridge.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "not supported"):
                bridge.login("qwen")
            run.assert_not_called()

    def test_copy_uses_stdin_not_command_arguments(self):
        self.configure()
        with patch.object(bridge.subprocess, "run") as run:
            bridge.copy_value("api-key")
        self.assertEqual(run.call_args.kwargs["input"], "client-secret")
        self.assertNotIn("client-secret", run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs["stdout"], bridge.subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["stderr"], bridge.subprocess.DEVNULL)
        self.assertTrue(run.call_args.kwargs["check"])

    def test_authenticated_requests_reject_redirects(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        received = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                received.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/redirected")
                self.end_headers()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                bridge.request(f"http://127.0.0.1:{server.server_port}/original", "fake-secret")
            self.assertEqual(error.exception.code, 302)
            error.exception.close()
            self.assertEqual(received, ["/original"])
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_api_uses_loopback_with_management_key(self):
        self.configure()
        with patch.object(bridge, "request", return_value={}) as request:
            bridge.api("auth-files/status", "PATCH", {"name": "x", "disabled": True})
        self.assertEqual(request.call_args.args, ("http://127.0.0.1:18317/v0/management/auth-files/status",
                         "management-secret", "PATCH", {"name": "x", "disabled": True}))


if __name__ == "__main__":
    unittest.main()
