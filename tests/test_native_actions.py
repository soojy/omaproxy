import json
import io
import subprocess
import threading
import concurrent.futures
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import omaproxy
import quotas


class NativeActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name)
        override = patch.object(omaproxy, "CONFIG", self.config)
        override.start()
        self.addCleanup(override.stop)

    def session(self):
        value = {"provider": "codex", "route": "codex", "state": "current-state", "status": "wait",
                 "url": "https://auth.example.test/authorize?state=current-state"}
        omaproxy.private_write(self.config / "oauth-session.json", json.dumps(value))
        return value

    def test_native_start_returns_no_oauth_state_or_url_to_qml(self):
        with patch.object(omaproxy, "api", return_value={"url": "https://auth.example.test/authorize", "state": "private-state"}) as api, \
             patch.object(omaproxy, "run") as run:
            result = omaproxy.auth_action("auth-start", "codex")
        self.assertEqual(api.call_args.args[0], "codex-auth-url?is_webui=true")
        self.assertEqual(run.call_args.args[0][0], "xdg-open")
        self.assertNotIn("private-state", json.dumps(result))
        self.assertEqual(result["auth"]["status"], "wait")

    def test_callback_rejects_wrong_session(self):
        self.session()
        with patch.object(omaproxy, "api") as api:
            with self.assertRaisesRegex(ValueError, "another sign-in"):
                omaproxy.auth_action("auth-callback", payload={"url": "http://localhost:1455/auth/callback?state=wrong&code=x"})
            api.assert_not_called()

    def test_callback_is_forwarded_to_backend(self):
        self.session()
        with patch.object(omaproxy, "api", return_value={}) as api:
            result = omaproxy.auth_action("auth-callback", payload={"url": "http://localhost:1455/auth/callback?state=current-state&code=private-code"})
        self.assertEqual(api.call_args.args[:2], ("oauth-callback", "POST"))
        self.assertNotIn("private-code", json.dumps(result))

    def test_cancel_clears_session(self):
        self.session()
        with patch.object(omaproxy, "api", return_value={}) as api:
            result = omaproxy.auth_action("auth-cancel")
        self.assertEqual(api.call_args.args[1], "DELETE")
        self.assertEqual(result["auth"]["status"], "")

    def test_poll_detects_completed_auth(self):
        self.session()
        with patch.object(omaproxy, "api", return_value={"status": "ok"}):
            result = omaproxy.auth_action("auth-status")
        self.assertEqual(result["auth"]["status"], "ok")

    def test_cache_reuses_fresh_reading(self):
        account = {"name": "account", "provider": "codex", "auth_index": "ref"}
        with patch.object(omaproxy, "api", return_value={"files": [account]}), \
             patch.object(quotas, "fetch", return_value={"windows": [{"remaining_percent": 90}], "error": ""}) as fetch:
            omaproxy.quota_snapshot()
            omaproxy.quota_snapshot()
            self.assertEqual(fetch.call_count, 1)

    def test_failed_refresh_retains_reading_as_stale(self):
        account = {"name": "account", "provider": "codex", "auth_index": "ref"}
        with patch.object(omaproxy, "api", return_value={"files": [account]}), \
             patch.object(quotas, "fetch", side_effect=[{"windows": [{"remaining_percent": 90}], "error": ""},
                                                        {"windows": [], "error": "Offline"}]):
            before = omaproxy.quota_snapshot()["quotas"]["accounts"][0]
            after = omaproxy.quota_snapshot(force=True)["quotas"]["accounts"][0]
        self.assertTrue(after["stale"])
        self.assertEqual(after["windows"], before["windows"])
        self.assertEqual(after["updated_at"], before["updated_at"])

    def test_poll_cannot_resurrect_cancelled_session(self):
        self.session()
        entered, release = threading.Event(), threading.Event()
        cancel_started, cancel_entered = threading.Event(), threading.Event()
        def api(route, *args, **kwargs):
            if route.startswith("get-auth-status"):
                entered.set()
                self.assertTrue(release.wait(2))
                return {"status": "wait"}
            cancel_entered.set()
            return {}
        with patch.object(omaproxy, "api", side_effect=api), concurrent.futures.ThreadPoolExecutor(2) as pool:
            poll = pool.submit(omaproxy.auth_action, "auth-status")
            self.assertTrue(entered.wait(2))
            def cancel_session():
                cancel_started.set()
                return omaproxy.auth_action("auth-cancel")
            cancel = pool.submit(cancel_session)
            self.assertTrue(cancel_started.wait(2))
            try:
                self.assertFalse(cancel_entered.wait(0.2), "Cancel must wait for the in-flight poll lock")
            finally:
                release.set()
            poll.result(timeout=3)
            cancel.result(timeout=3)
        self.assertEqual(omaproxy.read_json(self.config / "oauth-session.json", None), {})

    def test_browser_timeout_does_not_expose_signin_url(self):
        session = self.session()
        output = io.StringIO()
        with patch.object(omaproxy, "settings", return_value={"configured": True}), \
             patch.object(sys, "argv", ["omaproxy", "auth-open"]), \
             patch.object(omaproxy, "run", side_effect=subprocess.TimeoutExpired(["xdg-open", session["url"]], 20)), \
             patch.object(sys, "stdout", output):
            self.assertEqual(omaproxy.main(), 1)
        self.assertIn("timed out", output.getvalue())
        self.assertNotIn("current-state", output.getvalue())
        self.assertNotIn("https://", output.getvalue())

    def test_bad_account_preserves_cache_without_breaking_other_accounts(self):
        accounts = [{"name": n, "provider": "kimi", "auth_index": n} for n in ["bad", "good"]]
        old = {"accounts": [dict(accounts[0], windows=[{"remaining_percent": 90}], updated_at=123)]}
        omaproxy.private_write(self.config / "quotas.json", json.dumps(old))
        def fetch(account, api):
            if account["name"] == "bad":
                raise AttributeError("malformed provider record")
            return {"windows": [{"remaining_percent": 80}], "error": ""}
        with patch.object(omaproxy, "api", return_value={"files": accounts}), patch.object(quotas, "fetch", side_effect=fetch):
            result = omaproxy.quota_snapshot(force=True)["quotas"]["accounts"]
        self.assertTrue(result[0]["stale"])
        self.assertEqual(result[0]["updated_at"], 123)
        self.assertEqual(result[1]["windows"][0]["remaining_percent"], 80)

    def test_custom_provider_rejects_credential_url(self):
        with self.assertRaises(ValueError):
            omaproxy.custom_provider({"name": "demo", "url": "https://user:password@example.com/v1", "key": "private", "models": "test"})


if __name__ == "__main__":
    unittest.main()
