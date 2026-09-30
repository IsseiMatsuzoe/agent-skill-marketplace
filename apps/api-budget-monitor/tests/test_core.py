import unittest

from api_budget_monitor.core import ProviderSnapshot, format_money, format_percent


class ProviderSnapshotTests(unittest.TestCase):
    def test_percent_uses_reference_budget(self):
        snap = ProviderSnapshot("claude", "Claude", 4.0, 10.0)
        self.assertEqual(snap.percent, 40.0)
        self.assertEqual(snap.bar_percent, 40)
        self.assertEqual(snap.overflow_percent, 0.0)

    def test_percent_may_exceed_100_but_bar_caps(self):
        snap = ProviderSnapshot("openrouter", "OpenRouter", 15.0, 10.0)
        self.assertEqual(snap.percent, 150.0)
        self.assertEqual(snap.bar_percent, 100)
        self.assertEqual(snap.overflow_percent, 50.0)

    def test_unknown_balance_is_not_treated_as_zero(self):
        snap = ProviderSnapshot("xai", "Grok", None, 10.0)
        self.assertIsNone(snap.percent)
        self.assertEqual(format_money(None), "Unavailable")
        self.assertEqual(format_percent(None), "—")


if __name__ == "__main__":
    unittest.main()
