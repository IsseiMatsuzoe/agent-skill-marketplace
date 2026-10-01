from datetime import datetime, timezone
import json
import unittest
from unittest.mock import MagicMock, patch

from api_budget_monitor.core import KeyState
from api_budget_monitor.providers import HttpResult, _post_json, fetch_anthropic, fetch_xai


NOW = datetime(2026, 10, 1, 4, 30, tzinfo=timezone.utc)


def purchase(cents="-500", time="2026-09-29T06:52:06.656246Z"):
    return {"changeOrigin": "PURCHASE", "topupStatus": "SUCCEEDED",
            "amount": {"val": cents}, "createTime": time}


def ledger(*changes):
    changes = changes or (purchase(),)
    return {"total": {"val": str(sum(int(c["amount"]["val"]) for c in changes))}, "changes": list(changes)}


def preview(total="-500"):
    return {"billingCycle": {"year": 2026, "month": 10}, "effectiveSpendingLimit": "0", "defaultCredits": "0",
            "coreInvoice": {"prepaidCredits": {"val": total}, "prepaidCreditsUsed": {"val": "0"},
                            "autoCreditsIssued": "0", "defaultCreditsIssued": "0", "totalWithCorr": {"val": "0"}}}


def usage(value=2.820842):
    return {"limitReached": False, "timeSeries": [
        {"group": [], "dataPoints": [{"timestamp": "2026-09-29T00:00:00Z", "values": [value]}]}]}


class XaiBalanceTests(unittest.TestCase):
    def setUp(self):
        clock = patch("api_budget_monitor.providers.datetime", wraps=datetime)
        self.addCleanup(clock.stop)
        clock.start().now.return_value = NOW

    def fetch(self, balance=None, billing=None, spending=None, status=200):
        balance = ledger() if balance is None else balance
        billing = preview() if billing is None else billing
        spending = usage() if spending is None else spending
        with patch("api_budget_monitor.providers._get_json", side_effect=[
            HttpResult(status, balance), HttpResult(200, billing), HttpResult(200, {}),
        ]) as get, patch("api_budget_monitor.providers._post_json", return_value=HttpResult(200, spending)) as post:
            snap = fetch_xai({}, {"XAI_MANAGEMENT_API_KEY": "mgmt", "XAI_TEAM_ID": "team"})
        return snap, get, post

    def test_observed_purchase_minus_usage_is_estimated(self):
        snap, get, post = self.fetch()
        self.assertAlmostEqual(snap.remaining_usd, 2.179158)
        self.assertEqual(snap.balance_source, "estimated")
        self.assertIn("Reporting delay", snap.detail)
        self.assertEqual(get.call_count, 2)
        self.assertTrue(post.call_args.args[0].endswith("/usage"))
        query = post.call_args.args[2]["analyticsRequest"]
        self.assertEqual(query["values"], [{"name": "usd", "aggregation": "AGGREGATION_SUM"}])
        self.assertEqual(query["timeUnit"], "TIME_UNIT_NONE")
        self.assertEqual(query["groupBy"], [])
        self.assertEqual(query["filters"], [])
        self.assertEqual(query["timeRange"], {"startTime": "2026-09-29 06:52:06", "endTime": "2026-10-01 04:30:00", "timezone": "Etc/GMT"})

    def test_multiple_topups_include_usage_before_and_after_later_topup(self):
        data = ledger(purchase(), purchase("-1000", "2026-09-30T12:00:00Z"))
        snap, _, post = self.fetch(data, preview("-1500"), usage(6))
        self.assertEqual(snap.remaining_usd, 9)
        self.assertEqual(post.call_args.args[2]["analyticsRequest"]["timeRange"]["startTime"], "2026-09-29 06:52:06")

    def test_usage_window_longer_than_30_days_is_not_truncated(self):
        snap, _, post = self.fetch(ledger(purchase("-2000", "2026-08-01T12:00:00Z")), preview("-2000"), usage(14))
        self.assertEqual(snap.remaining_usd, 6)
        self.assertEqual(post.call_args.args[2]["analyticsRequest"]["timeRange"]["startTime"], "2026-08-01 12:00:00")

    def test_refunds_adjustments_promotions_and_settled_spend_are_unavailable(self):
        for origin in ("REFUND", "MANUAL", "SPEND", "PROMOTION", "EXPIRED", "MIGRATION"):
            change = purchase()
            change["changeOrigin"] = origin
            with self.subTest(origin=origin):
                snap, _, post = self.fetch(ledger(change))
                self.assertIsNone(snap.remaining_usd)
                self.assertEqual(snap.balance_source, "unavailable")
                post.assert_not_called()

    def test_zero_or_exhausted_credit_is_estimated_zero(self):
        for spent in (5, 8):
            with self.subTest(spent=spent):
                snap, _, _ = self.fetch(spending=usage(spent))
                self.assertEqual(snap.remaining_usd, 0)
                self.assertEqual(snap.balance_source, "estimated")

    def test_malformed_missing_truncated_and_nonfinite_usage_is_not_zero(self):
        bad = [{}, {"limitReached": False, "timeSeries": []}, [],
               {"limitReached": True, "timeSeries": usage()["timeSeries"]}]
        bad += [usage(v) for v in (None, True, "bad", "NaN", "Infinity", -1)]
        data = usage()
        data["timeSeries"][0]["dataPoints"][0]["values"] = []
        bad.append(data)
        for response in bad:
            with self.subTest(response=response):
                snap, _, _ = self.fetch(spending=response)
                self.assertIsNone(snap.remaining_usd)
                self.assertEqual(snap.balance_source, "unavailable")

    def test_management_auth_failure_does_not_become_zero_or_echo_body(self):
        for status in (401, 403):
            with self.subTest(status=status):
                snap, _, post = self.fetch(status=status, balance={"error": "PRIVATE"})
                self.assertIsNone(snap.remaining_usd)
                self.assertIn(f"HTTP {status}", snap.detail)
                self.assertNotIn("PRIVATE", snap.detail)
                post.assert_not_called()

    def test_missing_credentials_keep_manual_or_unavailable(self):
        for secrets in ({}, {"XAI_MANAGEMENT_API_KEY": "mgmt"}, {"XAI_TEAM_ID": "team"}):
            for cfg in ({}, {"manual_remaining_usd": 3}):
                with self.subTest(secrets=secrets, cfg=cfg), patch("api_budget_monitor.providers._get_json") as get:
                    snap = fetch_xai(cfg, secrets)
                    self.assertEqual(snap.remaining_usd, cfg.get("manual_remaining_usd"))
                    self.assertEqual(snap.balance_source, "manual" if cfg else "unavailable")
                    get.assert_not_called()

    def test_invalid_ledgers_never_fall_back_to_purchase_amount(self):
        bad = []
        for field, value in (("topupStatus", "TO_CHARGE"), ("createTime", "invalid"),
                             ("createTime", "2026-09-29T06:52:06"), ("expireTime", "2026-09-30T00:00:00Z"),
                             ("createTime", "2025-08-01T00:00:00Z"), ("createTime", "2027-01-01T00:00:00Z")):
            change = purchase()
            change[field] = value
            bad.append(ledger(change))
        for total in ("125", "0", "NaN", True, "-500.5", None):
            data = ledger()
            data["total"]["val"] = total
            bad.append(data)
        bad += [{"total": {"val": "0"}, "changes": []}, {"total": {"val": "-500"}}]
        for data in bad:
            with self.subTest(data=data):
                snap, _, post = self.fetch(data)
                self.assertIsNone(snap.remaining_usd)
                post.assert_not_called()

    def test_postpaid_promotional_adjusted_or_inconsistent_preview_is_unavailable(self):
        bad = []
        for key in ("effectiveSpendingLimit", "defaultCredits"):
            data = preview()
            data[key] = "1000"
            bad.append(data)
        for key in ("autoCreditsIssued", "defaultCreditsIssued"):
            data = preview()
            data["coreInvoice"][key] = "100"
            bad.append(data)
        for key in ("totalWithCorr", "prepaidCredits"):
            data = preview()
            data["coreInvoice"][key]["val"] = "200"
            bad.append(data)
        data = preview()
        data["billingCycle"]["month"] = 9
        bad += [data, {}]
        for data in bad:
            with self.subTest(data=data):
                snap, _, post = self.fetch(billing=data)
                self.assertIsNone(snap.remaining_usd)
                post.assert_not_called()

    def test_usage_or_preview_http_failure_keeps_safe_state_and_key_status(self):
        for status in (0, 401, 403, 500):
            with self.subTest(status=status), patch("api_budget_monitor.providers._get_json", side_effect=[
                HttpResult(200, ledger()), HttpResult(200, preview()), HttpResult(200, {}),
            ]), patch("api_budget_monitor.providers._post_json", return_value=HttpResult(status, None)):
                snap = fetch_xai({}, {"XAI_MANAGEMENT_API_KEY": "mgmt", "XAI_TEAM_ID": "team", "XAI_API_KEY": "api"})
                self.assertIsNone(snap.remaining_usd)
                self.assertEqual(snap.key_state, KeyState.ACTIVE)
        with patch("api_budget_monitor.providers._get_json", side_effect=[HttpResult(200, ledger()), HttpResult(403, None)]):
            snap = fetch_xai({}, {"XAI_MANAGEMENT_API_KEY": "mgmt", "XAI_TEAM_ID": "team"})
            self.assertIsNone(snap.remaining_usd)

    def test_usage_transport_is_json_post_and_malformed_json_is_unavailable(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = json.dumps(usage()).encode()
        with patch("api_budget_monitor.providers.urlopen", return_value=response) as open_url:
            result = _post_json("https://management-api.x.ai/v1/billing/teams/team/usage", {"Authorization": "Bearer dummy"}, {"analyticsRequest": {}})
        request = open_url.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), {"analyticsRequest": {}})
        self.assertEqual(result.payload, usage())
        response.read.return_value = b"invalid JSON"
        with patch("api_budget_monitor.providers.urlopen", return_value=response):
            self.assertIsNone(_post_json("https://example.test/usage", {}, {}).payload)

    def test_claude_manual_and_unavailable_behavior_is_unchanged(self):
        for cfg in ({}, {"manual_remaining_usd": 4}):
            with self.subTest(cfg=cfg), patch("api_budget_monitor.providers._get_json", return_value=HttpResult(200, {})) as get:
                snap = fetch_anthropic(cfg, {"ANTHROPIC_API_KEY": "api"})
            self.assertEqual(snap.remaining_usd, cfg.get("manual_remaining_usd"))
            self.assertEqual(snap.balance_source, "manual" if cfg else "unavailable")
            self.assertEqual(snap.key_state, KeyState.ACTIVE)
            self.assertEqual(get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
