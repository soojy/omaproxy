"""Status polls a synthetic loopback server; service control is always mocked."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import omaproxy as bridge


class StatusPollingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = patch.object(bridge, "CONFIG", Path(self.temp.name))
        override.start()
        self.addCleanup(override.stop)
        self.header = None
        self.paths = []
        test = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                test.paths.append(self.path)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                if self.path.endswith("auth-files") and test.header is not None:
                    self.send_header("x-CpA-VeRsIoN", test.header)
                self.end_headers()
                response = {"files": [{"name": "fixture", "access_token": "never-expose"}]} if self.path.endswith("auth-files") else {"data": [{"id": "fixture-model"}]}
                self.wfile.write(json.dumps(response).encode())
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_server)
        bridge.private_write(bridge.CONFIG / "settings.json", json.dumps({
            "port": self.server.server_port, "management_key": "fake-management",
            "api_key": "fake-client", "version": "v7.2.154", "providers": [],
        }))
        control = patch.object(bridge, "systemctl", return_value=subprocess.CompletedProcess([], 0, "active\n", ""))
        control.start()
        self.addCleanup(control.stop)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=2)

    def assert_single_poll(self, result):
        self.assertTrue(result["running"])
        self.assertEqual(result["error"], "")
        self.assertEqual(self.paths.count("/v0/management/auth-files"), 1)
        self.assertEqual(self.paths.count("/v1/models"), 1)
        self.assertEqual(result["models"], ["fixture-model"])
        self.assertNotIn("never-expose", json.dumps(result))

    def test_running_version_comes_from_the_existing_management_response(self):
        self.header = "8.0.13"
        result = bridge.status()
        self.assert_single_poll(result)
        self.assertEqual(result["version"], "v8.0.13")
        self.assertEqual(result["version_source"], "running")

    def test_missing_or_invalid_header_preserves_installed_version(self):
        for header in (None, "invalid version", "8.0.13 injected"):
            with self.subTest(header=header):
                self.header = header
                self.paths.clear()
                result = bridge.status()
                self.assert_single_poll(result)
                self.assertEqual(result["version"], "v7.2.154")
                self.assertNotIn("version_source", result)


if __name__ == "__main__":
    unittest.main()
