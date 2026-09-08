import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import quotas


class QuotaTests(unittest.TestCase):
    def test_codex_window_durations_not_positions(self):
        parsed = quotas.codex({"plan_type": "pro", "rate_limit": {
            "primary_window": {"used_percent": 3, "limit_window_seconds": 604800, "reset_at": 1800000000}},
            "additional_rate_limits": [{"limit_name": "Spark", "rate_limit": {
                "primary_window": {"used_percent": 0, "limit_window_seconds": 18000, "reset_after_seconds": 120}}}]}, now=1000)
        self.assertEqual(parsed["plan"], "pro")
        self.assertEqual(parsed["windows"][0]["label"], "Weekly")
        self.assertEqual(parsed["windows"][0]["remaining_percent"], 97)
        self.assertEqual(parsed["windows"][1]["label"], "Spark · 5-hour")
        self.assertEqual(parsed["windows"][1]["remaining_percent"], 100)
        self.assertEqual(parsed["windows"][1]["reset_at"], 1120)

    def test_unknown_is_not_zero_and_nonfinite_rejected(self):
        for value in (None, "NaN", "Infinity", "nonsense", True):
            self.assertIsNone(quotas.window("Test", value)["remaining_percent"])
        self.assertEqual(quotas.window("Exhausted", 110)["remaining_percent"], 0)

    def test_monthly_and_camel_case_payload(self):
        result = quotas.codex({"rateLimit": {"secondaryWindow": {"usedPercent": 45,
            "limitWindowSeconds": 2592000, "resetAt": 1800000000}}})
        self.assertEqual(result["windows"][0]["label"], "Monthly")
        self.assertEqual(result["windows"][0]["remaining_percent"], 55)

    def test_claude_limits_and_reset_timezone(self):
        result = quotas.claude({"five_hour": {"utilization": 20, "resets_at": "2026-09-08T10:00:00-04:00"},
                                "seven_day": {"utilization": None, "resets_at": None}})
        self.assertEqual(result["windows"][0]["remaining_percent"], 80)
        self.assertEqual(result["windows"][0]["reset_at"], quotas.reset_time("2026-09-08T14:00:00Z"))
        self.assertIsNone(result["windows"][1]["remaining_percent"])

    def test_kimi_remaining_and_relative_reset(self):
        result = quotas.kimi({"limits": [{"window": {"duration": 5, "timeUnit": "HOURS"},
            "detail": {"limit": 100, "remaining": 70, "reset_in": 60}}]}, now=1000)
        self.assertEqual(result["windows"][0]["remaining_percent"], 70)
        self.assertEqual(result["windows"][0]["reset_at"], 1060)

    def test_antigravity_fraction(self):
        result = quotas.antigravity({"groups": [{"displayName": "Claude", "buckets": [
            {"window": "weekly", "remainingFraction": 0.25, "resetTime": "2026-09-09T00:00:00Z"}]}]})
        self.assertEqual(result["windows"][0]["remaining_percent"], 25)

    def test_upstream_failure_never_claims_exhaustion(self):
        result = quotas.fetch({"provider": "codex", "auth_index": "ref"},
            Mock(return_value={"status_code": 429, "body": "secret error details"}))
        self.assertEqual(result["windows"], [])
        self.assertIn("rate-limited", result["error"])
        self.assertNotIn("secret", json.dumps(result))

    def test_backend_substitutes_token_and_account_id(self):
        call = Mock(return_value={"status_code": 200, "body": json.dumps({"rate_limit": {
            "primary_window": {"used_percent": 10, "limit_window_seconds": 18000}}})})
        result = quotas.fetch({"provider": "codex", "auth_index": "reference",
            "id_token": {"chatgpt_account_id": "account-id"}}, call)
        payload = call.call_args.args[2]
        self.assertEqual(payload["header"]["Authorization"], "Bearer $TOKEN$")
        self.assertEqual(payload["header"]["Chatgpt-Account-Id"], "account-id")
        self.assertEqual(result["windows"][0]["remaining_percent"], 90)
        self.assertNotIn("account-id", json.dumps(result))


    def test_malformed_nested_records_are_skipped(self):
        self.assertEqual(quotas.codex({"additional_rate_limits": [None, "bad"]})["windows"], [])
        self.assertEqual(quotas.kimi({"limits": [None, {"detail": "bad"}]})["windows"], [])
        self.assertEqual(quotas.antigravity({"groups": [None, {"buckets": [None]}]})["windows"], [])


if __name__ == "__main__":
    unittest.main()
