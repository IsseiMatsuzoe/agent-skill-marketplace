import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# No interactive desktop or provider credentials are needed in CI.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QSystemTrayIcon

from api_budget_monitor.core import KeyState, ProviderSnapshot
from api_budget_monitor.ui import APP_STYLE, BudgetMonitorApp, BudgetPopup, SettingsDialog


class FlyoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        # Suppress scheduled background work; all refresh results below are local.
        with patch("api_budget_monitor.ui.QTimer.singleShot"):
            self.monitor = BudgetMonitorApp(self.app, Path(self.directory.name))
        self.monitor.timer.stop()
        self.monitor.runtime_timer.stop()
        self.popup = self.monitor.popup
        self.monitor.tray.hide()

    def tearDown(self):
        self.popup.close()
        self.popup.deleteLater()
        self.monitor.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.directory.cleanup()

    def open_popup(self):
        self.monitor._tray_activated(QSystemTrayIcon.Trigger)
        self.app.processEvents()
        # Offscreen CI does not provide a real window manager.
        self.app.sendEvent(self.popup, QEvent(QEvent.WindowActivate))
        self.assertTrue(self.popup.isVisible())

    def deactivate(self):
        self.app.sendEvent(self.popup, QEvent(QEvent.WindowDeactivate))

    def test_tray_toggle_and_escape_from_child(self):
        self.open_popup()
        self.monitor._tray_activated(QSystemTrayIcon.Trigger)
        self.assertFalse(self.popup.isVisible())
        self.open_popup()
        button = self.popup.findChildren(QPushButton)[0]
        button.setFocus()
        QTest.keyClick(button, Qt.Key_Escape)
        self.app.processEvents()
        self.assertFalse(self.popup.isVisible())

    def test_internal_click_focus_changes_and_mouse_move_keep_open(self):
        self.open_popup()
        buttons = {button.text(): button for button in self.popup.findChildren(QPushButton)}
        refresh, settings = buttons["Refresh"], buttons["Settings"]
        with patch.object(self.monitor.pool, "start") as start:
            QTest.mouseClick(refresh, Qt.LeftButton)
            self.assertEqual(start.call_count, 1)
        refresh.setFocus()
        self.app.processEvents()
        settings.setFocus()
        self.app.processEvents()
        self.app.sendEvent(refresh, QFocusEvent(QEvent.FocusOut, Qt.TabFocusReason))
        self.app.sendEvent(self.popup, QFocusEvent(QEvent.FocusOut, Qt.OtherFocusReason))
        QTest.mouseMove(settings)
        self.assertTrue(self.popup.isVisible())

    def test_window_deactivation_hides_immediately_and_next_click_opens(self):
        self.open_popup()
        with patch.object(self.monitor.tray, "geometry", return_value=QRect()):
            self.deactivate()
        self.assertFalse(self.popup.isVisible())
        self.open_popup()

    def test_deactivation_before_initial_activation_is_ignored(self):
        # Hold window-manager events to exercise the opening transition.
        with patch.object(self.popup, "activateWindow"):
            self.monitor.toggle_popup()
            self.deactivate()
            self.assertTrue(self.popup.isVisible())
            self.app.sendEvent(self.popup, QEvent(QEvent.WindowActivate))
            self.deactivate()
            self.assertFalse(self.popup.isVisible())

    def test_tray_deactivation_then_release_does_not_reopen(self):
        self.open_popup()
        with patch.object(self.monitor.tray, "geometry", return_value=QRect(0, 0, 24, 24)), \
             patch("api_budget_monitor.ui.QCursor.pos", return_value=QPoint(12, 12)), \
             patch("api_budget_monitor.ui.monotonic", return_value=10.0):
            self.deactivate()
            self.assertFalse(self.popup.isVisible())
            self.monitor._tray_activated(QSystemTrayIcon.Trigger)
        self.assertFalse(self.popup.isVisible())
        self.open_popup()

    def test_deactivation_during_raise_does_not_hide_opening_flyout(self):
        def raise_window():
            self.app.sendEvent(self.popup, QEvent(QEvent.WindowActivate))
            self.deactivate()
            self.assertTrue(self.popup.isVisible())

        with patch.object(self.popup, "raise_", raise_window):
            self.monitor.toggle_popup()
        self.app.sendEvent(self.popup, QEvent(QEvent.WindowActivate))
        self.deactivate()
        self.assertFalse(self.popup.isVisible())

    def test_tray_guard_expires_and_context_activation_clears_it(self):
        self.monitor._tray_dismissed_at = 10.0
        with patch("api_budget_monitor.ui.monotonic", return_value=20.0):
            self.monitor._tray_activated(QSystemTrayIcon.Trigger)
        self.assertTrue(self.popup.isVisible())
        self.popup.hide()
        self.monitor._tray_dismissed_at = 10.0
        self.monitor._tray_activated(QSystemTrayIcon.Context)
        self.assertIsNone(self.monitor._tray_dismissed_at)
        self.assertFalse(self.popup.isVisible())

    def test_settings_hides_first_and_is_released_without_reopening(self):
        self.open_popup()
        observed = []

        def exec_dialog(dialog):
            observed.append((self.popup.isVisible(), dialog.parent()))
            return QDialog.Rejected

        with patch.object(SettingsDialog, "exec", exec_dialog):
            self.popup.request_settings.emit()
        self.assertEqual(observed, [(False, None)])
        self.assertFalse(self.popup.isVisible())
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(any(isinstance(w, SettingsDialog) for w in self.app.topLevelWidgets()))

    def test_repeated_open_dismiss_reuses_window_and_one_refresh_handler(self):
        identity = self.popup
        for _ in range(50):
            self.open_popup()
            with patch.object(self.monitor.tray, "geometry", return_value=QRect()):
                self.deactivate()
            self.assertFalse(self.popup.isVisible())
            self.assertIs(self.monitor.popup, identity)
        self.assertEqual(sum(isinstance(w, BudgetPopup) for w in self.app.topLevelWidgets()), 1)
        with patch.object(self.monitor.pool, "start") as start:
            self.popup.request_refresh.emit()
        self.assertEqual(start.call_count, 1)

    def test_refresh_updates_hidden_cards_without_showing_or_changing_style(self):
        snapshots = [
            ProviderSnapshot("anthropic", "Claude", 4.0, 10.0, KeyState.ACTIVE, balance_source="manual"),
            ProviderSnapshot("xai", "Grok", None, 10.0, KeyState.MISSING),
            ProviderSnapshot("openrouter", "OpenRouter", 15.0, 10.0, KeyState.ACTIVE),
        ]
        self.monitor._refresh_done(snapshots)
        self.assertFalse(self.popup.isVisible())
        self.assertEqual(self.popup.cards["anthropic"].gauge.value(), 40)
        self.assertIn("Manual", self.popup.cards["anthropic"].amount_label.text())
        self.assertEqual(self.popup.cards["xai"].amount_label.text(), "Unavailable")
        self.assertEqual(self.popup.cards["openrouter"].percent_label.text(), "150%")
        self.assertEqual(self.popup.cards["openrouter"].gauge.value(), 100)
        self.assertEqual(self.popup.styleSheet(), APP_STYLE)

    def test_runtime_card_displays_read_only_gate_state(self):
        from api_budget_monitor.runtime import RuntimeSnapshot

        self.monitor._runtime_done(RuntimeSnapshot("Running", "Connected", False))
        self.assertEqual(self.popup.runtime_card.backend_label.text(), "Running")
        self.assertEqual(self.popup.runtime_card.tunnel_label.text(), "Connected")
        self.assertEqual(self.popup.runtime_card.paid_label.text(), "Disabled")


if __name__ == "__main__":
    unittest.main()
