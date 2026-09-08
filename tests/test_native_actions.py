import json
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

    def test_custom_provider_rejects_credential_url(self):
        with self.assertRaises(ValueError):
            omaproxy.custom_provider({"name": "demo", "url": "https://user:password@example.com/v1", "key": "private", "models": "test"})


if __name__ == "__main__":
    unittest.main()
