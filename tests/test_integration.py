"""Real backend, fake upstream. Run with OMAPROXY_TEST_BINARY=/path/to/cli-proxy-api."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import omaproxy
import urllib.error
import urllib.request


@unittest.skipUnless(os.environ.get("OMAPROXY_TEST_BINARY"), "set OMAPROXY_TEST_BINARY for real-backend tests")
class BackendIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.received = []

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                cls.received.append((self.path, self.headers.get("Authorization"), body))
                if body.get("stream"):
                    result = b'data: {"id":"test","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"hello"}}]}\n\ndata: [DONE]\n\n'
                    content_type = "text/event-stream"
                else:
                    result = json.dumps({"id": "test", "object": "chat.completion", "model": "mock-model",
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode()
                    content_type = "application/json"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(result)))
                self.end_headers()
                self.wfile.write(result)

        cls.upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        cls.addClassCleanup(cls.upstream.server_close)
        cls.addClassCleanup(cls.upstream.shutdown)
        threading.Thread(target=cls.upstream.serve_forever, daemon=True).start()
        with contextlib.closing(socket.socket()) as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.cfg = {"host": "127.0.0.1", "port": cls.port,
            "auth-dir": str(Path(cls.temp.name) / "auth"),
            "api-keys": ["test-client-key"],
            "remote-management": {"secret-key": "test-management-key", "allow-remote": False, "disable-control-panel": True},
            "openai-compatibility": [{"name": "mock", "base-url": f"http://127.0.0.1:{cls.upstream.server_port}/v1",
                "api-key-entries": [{"api-key": "test-upstream-key"}],
                "models": [{"name": "mock-model", "alias": "test-model"}]}]}
        config = Path(cls.temp.name) / "config.yaml"
        config.write_text(json.dumps(cls.cfg))
        cls.process = subprocess.Popen([os.environ["OMAPROXY_TEST_BINARY"], "--config", str(config), "--local-model"],
            cwd=cls.temp.name, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_backend)
        for _ in range(100):
            if cls.process.poll() is not None:
                raise RuntimeError("Test backend exited before becoming ready")
            try:
                cls.call("/v1/models")
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        else:
            raise RuntimeError("Test backend never became ready")

    @classmethod
    def stop_backend(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait()

    @classmethod
    def call(cls, path, body=None, key="test-client-key", raw=False):
        req = urllib.request.Request(cls.base + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.read() if raw else json.load(response)

    def test_model_discovery(self):
        self.assertIn("test-model", [x["id"] for x in self.call("/v1/models")["data"]])

    def test_management_key_is_separate_from_client_key(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.call("/v0/management/auth-files")
        self.assertEqual(error.exception.code, 401)
        error.exception.close()
        self.assertEqual(self.call("/v0/management/auth-files", key="test-management-key")["files"], [])

    def test_routes_completion_and_alias_to_mock_upstream(self):
        result = self.call("/v1/chat/completions", {"model": "test-model", "messages": [{"role": "user", "content": "Hi"}]})
        self.assertEqual(result["choices"][0]["message"]["content"], "hello")
        path, key, body = self.received[-1]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(key, "Bearer test-upstream-key")
        self.assertEqual(body["model"], "mock-model")

    def test_bridge_adds_provider_without_replacing_existing_entries(self):
        cfg = {"port": self.port, "api_key": "test-client-key", "management_key": "test-management-key"}
        with patch.object(omaproxy, "settings", return_value=cfg), patch.object(omaproxy, "CONFIG", Path(self.temp.name)):
            result = omaproxy.custom_provider({"name": "added", "url": f"http://127.0.0.1:{self.upstream.server_port}/v1",
                "key": "fake-added-key", "models": "added-model"})
            self.assertIn("added", result["message"])
            entries = omaproxy.api("openai-compatibility")["openai-compatibility"]
        self.assertEqual({entry["name"] for entry in entries}, {"mock", "added"})

    def test_bridge_changes_routing_strategy(self):
        cfg = {"port": self.port, "api_key": "test-client-key", "management_key": "test-management-key"}
        with patch.object(omaproxy, "settings", return_value=cfg):
            try:
                omaproxy.api("routing/strategy", "PUT", {"value": "fill-first"})
                self.assertEqual(omaproxy.api("routing/strategy")["strategy"], "fill-first")
            finally:
                omaproxy.api("routing/strategy", "PUT", {"value": "round-robin"})

    def test_streaming_completion(self):
        result = self.call("/v1/chat/completions", {"model": "test-model", "stream": True,
            "messages": [{"role": "user", "content": "Hi"}]}, raw=True)
        self.assertIn(b"hello", result)
        self.assertIn(b"[DONE]", result)


if __name__ == "__main__":
    unittest.main()
