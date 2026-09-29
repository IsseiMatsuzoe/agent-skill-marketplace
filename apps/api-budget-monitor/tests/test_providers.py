import unittest
from unittest.mock import patch

from api_budget_monitor.core import KeyState
from api_budget_monitor.providers import HttpResult, fetch_openrouter, fetch_xai


class ProviderParsingTests(unittest.TestCase):
    def test_openrouter_credits_are_purchased_minus_usage(self):
        responses = [
            HttpResult(200, {"data": {"total_credits": 10.0, "total_usage": 6.0}}),
            HttpResult(200, {"data": {"expires_at": "2026-10-30T00:00:00Z"}}),
        ]
        with patch("api_budget_monitor.providers._get_json", side_effect=responses):
            snap = fetch_openrouter(
                {"reference_budget_usd": 10.0},
                {"OPENROUTER_MANAGEMENT_KEY": "mgmt", "OPENROUTER_API_KEY": "api"},
            )
        self.assertEqual(snap.remaining_usd, 4.0)
        self.assertEqual(snap.key_state, KeyState.ACTIVE)
        self.assertEqual(snap.key_valid_until, "2026-10-30T00:00:00Z")

    def test_xai_documented_negative_credit_accounting_maps_to_positive_balance(self):
        responses = [
            HttpResult(200, {"total": {"val": "-450"}}),
            HttpResult(200, {"data": []}),
        ]
        with patch("api_budget_monitor.providers._get_json", side_effect=responses):
            snap = fetch_xai(
                {"reference_budget_usd": 10.0},
                {"XAI_MANAGEMENT_API_KEY": "mgmt", "XAI_TEAM_ID": "team", "XAI_API_KEY": "api"},
            )
        self.assertEqual(snap.remaining_usd, 4.5)
        self.assertEqual(snap.key_state, KeyState.ACTIVE)


if __name__ == "__main__":
    unittest.main()
