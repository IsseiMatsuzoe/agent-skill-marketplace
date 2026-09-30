from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QEvent, QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QColor, QCursor, QDesktopServices, QIcon, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QMenu,
    QPushButton,
    QLineEdit,
    QProgressBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QUrl

from .config import AppConfig, ensure_config, save_config
from .core import KeyState, ProviderSnapshot, compact_until, format_money, format_percent
from .providers import fetch_all
from .runtime import (
    RuntimeManager,
    RuntimeSnapshot,
    PROFILE_NAME_RE,
    runtime_transition_messages,
    save_tunnel_credential,
    service_path,
    runtime_directory,
)


APP_STYLE = """
QWidget { background: #171717; color: #f5f5f5; font-family: "Segoe UI"; font-size: 13px; }
QFrame#card { background: #202020; border: 1px solid #303030; border-radius: 12px; }
QLabel#provider { font-size: 15px; font-weight: 600; }
QLabel#money { font-size: 22px; font-weight: 650; }
QLabel#percent { font-size: 14px; font-weight: 600; color: #d6d6d6; }
QLabel#muted { color: #9b9b9b; font-size: 11px; }
QLabel#overflow { background: #303030; border-radius: 8px; padding: 2px 6px; color: #d8d8d8; font-size: 10px; }
QProgressBar { border: none; background: #343434; border-radius: 5px; height: 10px; text-align: center; }
QProgressBar::chunk { background: #e6e6e6; border-radius: 5px; }
QPushButton { background: #2b2b2b; border: 1px solid #3b3b3b; border-radius: 8px; padding: 6px 10px; }
QPushButton:hover { background: #353535; }
QDoubleSpinBox { background: #252525; border: 1px solid #3a3a3a; border-radius: 6px; padding: 4px; }
"""


class WorkerSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class RefreshWorker(QRunnable):
    def __init__(self, providers_cfg: dict[str, dict], secrets: dict[str, str]):
        super().__init__()
        self.providers_cfg = providers_cfg
        self.secrets = secrets
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.done.emit(fetch_all(self.providers_cfg, self.secrets))
        except Exception as exc:  # UI boundary: surface unexpected failures without crashing tray app.
            self.signals.failed.emit(str(exc))


class RuntimeWorker(QRunnable):
    def __init__(self, manager: RuntimeManager, action: str):
        super().__init__()
        self.manager = manager
        self.action = action
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            if self.action == "start":
                result = self.manager.start()
            elif self.action == "restart":
                result = self.manager.restart()
            else:
                result = self.manager.snapshot()
            self.signals.done.emit(result)
        except Exception:
            # Runtime paths and third-party process errors are deliberately not echoed into the UI.
            self.signals.failed.emit("Runtime status is unavailable.")


class ProviderCard(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(340)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)

        top = QHBoxLayout()
        self.provider_label = QLabel("Provider")
        self.provider_label.setObjectName("provider")
        self.percent_label = QLabel("—")
        self.percent_label.setObjectName("percent")
        top.addWidget(self.provider_label)
        top.addStretch(1)
        top.addWidget(self.percent_label)
        layout.addLayout(top)

        self.gauge = QProgressBar()
        self.gauge.setRange(0, 100)
        self.gauge.setTextVisible(False)
        layout.addWidget(self.gauge)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(10)
        self.amount_label = QLabel("Unavailable")
        self.amount_label.setObjectName("amount")
        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        meta_row.addWidget(self.amount_label)
        meta_row.addStretch(1)
        meta_row.addWidget(self.status_label)
        layout.addLayout(meta_row)

    def update_snapshot(self, snapshot: ProviderSnapshot) -> None:
        self.provider_label.setText(snapshot.display_name)
        self.percent_label.setText(format_percent(snapshot.percent))
        self.gauge.setValue(snapshot.bar_percent)

        if snapshot.remaining_usd is None:
            amount_text = "Unavailable"
        else:
            amount_text = (
                f"{format_money(snapshot.remaining_usd)} of ${snapshot.reference_budget_usd:g}"
            )
            if snapshot.balance_source == "manual":
                amount_text += " · Manual"
        self.amount_label.setText(amount_text)

        if snapshot.percent is None:
            self.gauge.setEnabled(False)
        else:
            self.gauge.setEnabled(True)

        state_text = {
            KeyState.ACTIVE: "Key active",
            KeyState.INVALID: "Key invalid",
            KeyState.MISSING: "Key not configured",
            KeyState.UNKNOWN: "Key status unknown",
        }[snapshot.key_state]
        until = compact_until(snapshot.key_valid_until)
        if until:
            state_text += f" · until {until}"
        self.status_label.setText(state_text)
        self.status_label.setToolTip(snapshot.detail or "")


class RuntimeCard(QFrame):
    request_start = Signal()
    request_restart = Signal()
    request_open_logs = Signal()
    request_open_external_agents = Signal()
    request_setup_tunnel_auth = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)

        title = QLabel("External Agents")
        title.setObjectName("provider")
        layout.addWidget(title)

        form = QFormLayout()
        self.backend_label = QLabel("Checking…")
        self.tunnel_label = QLabel("Checking…")
        self.paid_label = QLabel("Unknown")
        for label in (self.backend_label, self.tunnel_label, self.paid_label):
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.addRow("Backend", self.backend_label)
        form.addRow("Tunnel", self.tunnel_label)
        form.addRow("Paid calls", self.paid_label)
        layout.addLayout(form)

        controls = QHBoxLayout()
        self.start_button = QPushButton("Start runtime")
        self.restart_button = QPushButton("Restart runtime")
        self.start_button.clicked.connect(self.request_start)
        self.restart_button.clicked.connect(self.request_restart)
        controls.addWidget(self.start_button)
        controls.addWidget(self.restart_button)
        layout.addLayout(controls)

        links = QHBoxLayout()
        logs = QPushButton("Open logs")
        folder = QPushButton("Open External Agents folder")
        auth = QPushButton("Set up tunnel auth")
        logs.clicked.connect(self.request_open_logs)
        folder.clicked.connect(self.request_open_external_agents)
        auth.clicked.connect(self.request_setup_tunnel_auth)
        links.addWidget(logs)
        links.addWidget(folder)
        links.addWidget(auth)
        layout.addLayout(links)

    def set_snapshot(self, snapshot: RuntimeSnapshot) -> None:
        self.backend_label.setText(snapshot.backend)
        self.tunnel_label.setText(snapshot.tunnel)
        self.paid_label.setText("Enabled" if snapshot.paid_calls_enabled is True else "Disabled" if snapshot.paid_calls_enabled is False else "Unknown")
        self.backend_label.setToolTip(snapshot.backend_detail)
        self.tunnel_label.setToolTip(snapshot.tunnel_detail)

    def set_busy(self, busy: bool) -> None:
        self.start_button.setEnabled(not busy)
        self.restart_button.setEnabled(not busy)


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, config_path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config
        self.config_path = config_path
        self.setWindowTitle("API Budget settings")
        self.setMinimumWidth(540)
        self.setStyleSheet(APP_STYLE)

        root = QVBoxLayout(self)
        form = QFormLayout()
        self.budget_inputs: dict[str, QDoubleSpinBox] = {}
        self.manual_inputs: dict[str, QDoubleSpinBox] = {}
        self.until_inputs: dict[str, QLineEdit] = {}

        for provider_id in ("anthropic", "xai", "openrouter"):
            cfg = self.config.providers[provider_id]
            budget = QDoubleSpinBox()
            budget.setRange(0.01, 100000.0)
            budget.setDecimals(2)
            budget.setPrefix("$")
            budget.setValue(float(cfg.get("reference_budget_usd", 10.0)))
            self.budget_inputs[provider_id] = budget
            form.addRow(f"{cfg.get('display_name', provider_id)} reference", budget)

            until = QLineEdit()
            until.setPlaceholderText("YYYY-MM-DD (optional)")
            until.setText(str(cfg.get("key_valid_until") or ""))
            self.until_inputs[provider_id] = until
            form.addRow(f"{cfg.get('display_name', provider_id)} key until", until)

        claude_manual = QDoubleSpinBox()
        claude_manual.setRange(-1.0, 100000.0)
        claude_manual.setDecimals(2)
        claude_manual.setPrefix("$")
        claude_manual.setSpecialValueText("Unavailable")
        current = self.config.providers["anthropic"].get("manual_remaining_usd")
        claude_manual.setValue(float(current) if current is not None else -1.0)
        self.manual_inputs["anthropic"] = claude_manual
        form.addRow("Claude manual balance", claude_manual)

        root.addLayout(form)

        runtime_form = QFormLayout()
        self.runtime_enabled = QCheckBox("Start External Agents with API Budget")
        self.runtime_enabled.setChecked(config.external_agents.enabled_on_startup)
        runtime_form.addRow("Automatic startup", self.runtime_enabled)

        self.service_path_input = QLineEdit(config.external_agents.service_path)
        self.service_path_input.setPlaceholderText("Automatic: repository services/external-agents")
        service_row = QHBoxLayout()
        service_row.addWidget(self.service_path_input, 1)
        service_browse = QPushButton("Browse…")
        service_browse.clicked.connect(self._browse_service)
        service_row.addWidget(service_browse)
        runtime_form.addRow("External Agents service", service_row)

        self.tunnel_profile_input = QLineEdit(config.external_agents.tunnel_profile)
        runtime_form.addRow("Tunnel profile", self.tunnel_profile_input)

        self.tunnel_client_input = QLineEdit(config.external_agents.tunnel_client_path)
        self.tunnel_client_input.setPlaceholderText("Automatic: service .local/tunnel-client/tunnel-client.exe")
        client_row = QHBoxLayout()
        client_row.addWidget(self.tunnel_client_input, 1)
        client_browse = QPushButton("Browse…")
        client_browse.clicked.connect(self._browse_tunnel_client)
        client_row.addWidget(client_browse)
        runtime_form.addRow("Tunnel client", client_row)

        runtime_note = QLabel(
            "Enable the existing API Budget startup shortcut with install.ps1 -EnableStartup. "
            "The tunnel key is stored in Windows Credential Manager; it is never written to settings or logs."
        )
        runtime_note.setWordWrap(True)
        runtime_note.setObjectName("muted")
        runtime_form.addRow("", runtime_note)
        root.addWidget(QLabel("External Agents runtime"))
        root.addLayout(runtime_form)

        note = QLabel("Provider keys and key rotation dates stay in the local config folder; keys are never displayed here.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        root.addWidget(note)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        save = QPushButton("Save")
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def _save(self) -> None:
        profile = self.tunnel_profile_input.text().strip() or "external-agents"
        if not PROFILE_NAME_RE.fullmatch(profile):
            QMessageBox.warning(self, "Invalid tunnel profile", "Use 1–64 letters, numbers, hyphens, or underscores.")
            return
        for provider_id, widget in self.budget_inputs.items():
            self.config.providers[provider_id]["reference_budget_usd"] = widget.value()
            until = self.until_inputs[provider_id].text().strip()
            self.config.providers[provider_id]["key_valid_until"] = until or None
        manual = self.manual_inputs["anthropic"].value()
        self.config.providers["anthropic"]["manual_remaining_usd"] = None if manual < 0 else manual
        self.config.external_agents.enabled_on_startup = self.runtime_enabled.isChecked()
        self.config.external_agents.service_path = self.service_path_input.text().strip()
        self.config.external_agents.tunnel_profile = profile
        self.config.external_agents.tunnel_client_path = self.tunnel_client_input.text().strip()
        save_config(self.config_path, self.config)
        self.accept()

    def _browse_service(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select External Agents service folder", self.service_path_input.text())
        if path:
            self.service_path_input.setText(path)

    def _browse_tunnel_client(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select tunnel-client executable", self.tunnel_client_input.text(), "Executable (*.exe);;All files (*)")
        if path:
            self.tunnel_client_input.setText(path)


class BudgetPopup(QWidget):
    request_refresh = Signal()
    request_settings = Signal()
    request_runtime_start = Signal()
    request_runtime_restart = Signal()
    request_open_logs = Signal()
    request_open_external_agents = Signal()
    request_setup_tunnel_auth = Signal()
    deactivated = Signal()

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self._activation_seen = False
        self._opening = False
        self._escape = QShortcut(Qt.Key_Escape, self)
        self._escape.activated.connect(self.hide)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setStyleSheet(APP_STYLE)
        self.setWindowTitle("API Budget")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(9)

        header = QHBoxLayout()
        title = QLabel("API Budget")
        title.setStyleSheet("font-size: 17px; font-weight: 650;")
        self.updated_label = QLabel("Not updated")
        self.updated_label.setObjectName("muted")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.updated_label)
        root.addLayout(header)

        self.runtime_card = RuntimeCard()
        self.runtime_card.request_start.connect(self.request_runtime_start)
        self.runtime_card.request_restart.connect(self.request_runtime_restart)
        self.runtime_card.request_open_logs.connect(self.request_open_logs)
        self.runtime_card.request_open_external_agents.connect(self.request_open_external_agents)
        self.runtime_card.request_setup_tunnel_auth.connect(self.request_setup_tunnel_auth)
        root.addWidget(self.runtime_card)

        self.cards: dict[str, ProviderCard] = {}
        for provider_id in ("anthropic", "xai", "openrouter"):
            card = ProviderCard()
            self.cards[provider_id] = card
            root.addWidget(card)

        footer = QHBoxLayout()
        refresh = QPushButton("Refresh")
        settings = QPushButton("Settings")
        refresh.clicked.connect(self.request_refresh)
        settings.clicked.connect(self.request_settings)
        footer.addWidget(refresh)
        footer.addStretch(1)
        footer.addWidget(settings)
        root.addLayout(footer)

        self.adjustSize()

    def set_snapshots(self, snapshots: list[ProviderSnapshot]) -> None:
        for snapshot in snapshots:
            if snapshot.provider_id in self.cards:
                self.cards[snapshot.provider_id].update_snapshot(snapshot)
        self.updated_label.setText(datetime.now().strftime("Updated %H:%M"))
        self.adjustSize()

    def set_runtime_snapshot(self, snapshot: RuntimeSnapshot) -> None:
        self.runtime_card.set_snapshot(snapshot)

    def show_near_cursor(self) -> None:
        self.adjustSize()
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        available = screen.availableGeometry()
        cursor = QCursor.pos()
        x = min(cursor.x() - self.width() + 24, available.right() - self.width())
        y = min(cursor.y() - self.height() - 12, available.bottom() - self.height())
        x = max(available.left(), x)
        y = max(available.top(), y)
        self.move(x, y)
        # Raising a Windows tool window can transiently deactivate it before
        # activateWindow() completes. Treat this synchronous sequence as one open.
        self._opening = True
        try:
            self.show()
            self.raise_()
            self.activateWindow()
        finally:
            self._opening = False

    def event(self, event) -> bool:
        if event.type() == QEvent.WindowActivate and self.isVisible():
            self._activation_seen = True
        elif (event.type() == QEvent.WindowDeactivate and self.isVisible()
              and self._activation_seen and not self._opening):
            self.deactivated.emit()
            self.hide()
        return super().event(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._activation_seen = False
        super().hideEvent(event)


def make_tray_icon() -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#202020"))
    painter.setPen(QPen(QColor("#d8d8d8"), 2))
    painter.drawEllipse(4, 4, 24, 24)
    painter.setPen(QPen(QColor("#f2f2f2"), 2.5, Qt.SolidLine, Qt.RoundCap))
    painter.drawArc(8, 8, 16, 16, 30 * 16, 250 * 16)
    painter.end()
    return QIcon(pixmap)


class BudgetMonitorApp(QObject):
    def __init__(self, qt_app: QApplication, config_dir: Path):
        super().__init__()
        self.qt_app = qt_app
        self.config_dir = config_dir
        self.config_path = config_dir / "settings.json"
        self.config, self.secrets = ensure_config(config_dir)
        self.runtime_manager = RuntimeManager(config_dir, self.config)
        self._runtime_busy = False
        self._runtime_snapshot: RuntimeSnapshot | None = None
        self.pool = QThreadPool.globalInstance()
        self.popup = BudgetPopup()
        self._tray_dismissed_at: float | None = None
        self.popup.request_refresh.connect(self.refresh)
        self.popup.request_settings.connect(self.open_settings)
        self.popup.request_runtime_start.connect(lambda: self._run_runtime("start"))
        self.popup.request_runtime_restart.connect(lambda: self._run_runtime("restart"))
        self.popup.request_open_logs.connect(self.open_runtime_logs)
        self.popup.request_open_external_agents.connect(self.open_external_agents_folder)
        self.popup.request_setup_tunnel_auth.connect(self.setup_tunnel_auth)
        self.popup.deactivated.connect(self._popup_deactivated)

        self.tray = QSystemTrayIcon(make_tray_icon(), self.qt_app)
        self.tray.setToolTip("API Budget")
        menu = QMenu()
        show_action = QAction("Show API Budget", menu)
        refresh_action = QAction("Refresh", menu)
        settings_action = QAction("Settings", menu)
        folder_action = QAction("Open config folder", menu)
        quit_action = QAction("Quit", menu)
        show_action.triggered.connect(self.toggle_popup)
        refresh_action.triggered.connect(self.refresh)
        settings_action.triggered.connect(self.open_settings)
        folder_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.config_dir))))
        quit_action.triggered.connect(self.qt_app.quit)
        menu.addAction(show_action)
        menu.addAction(refresh_action)
        menu.addSeparator()
        menu.addAction(settings_action)
        menu.addAction(folder_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self._reset_timer()
        QTimer.singleShot(200, self.refresh)

        self.runtime_timer = QTimer(self)
        self.runtime_timer.setInterval(15_000)
        self.runtime_timer.timeout.connect(self.poll_runtime)
        self.runtime_timer.start()
        if self.config.external_agents.enabled_on_startup:
            QTimer.singleShot(250, lambda: self._run_runtime("start"))
        else:
            QTimer.singleShot(250, self.poll_runtime)

    def _reset_timer(self) -> None:
        self.timer.start(max(1, self.config.refresh_minutes) * 60 * 1000)

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        dismissed_at = self._tray_dismissed_at
        self._tray_dismissed_at = None
        if reason == QSystemTrayIcon.Trigger:
            # Windows may deactivate on press, then deliver Trigger on release.
            # Consume that click, but never suppress a later click indefinitely.
            if dismissed_at is not None and monotonic() - dismissed_at <= self.qt_app.doubleClickInterval() / 1000:
                return
            self.toggle_popup()

    def _popup_deactivated(self) -> None:
        self._tray_dismissed_at = monotonic() if self.tray.geometry().contains(QCursor.pos()) else None

    def toggle_popup(self) -> None:
        self._tray_dismissed_at = None
        if self.popup.isVisible():
            self.popup.hide()
        else:
            self.popup.show_near_cursor()

    def refresh(self) -> None:
        self.config, self.secrets = ensure_config(self.config_dir)
        worker = RefreshWorker(self.config.providers, self.secrets)
        worker.signals.done.connect(self._refresh_done)
        worker.signals.failed.connect(self._refresh_failed)
        self.pool.start(worker)

    def _refresh_done(self, snapshots: list[ProviderSnapshot]) -> None:
        self.popup.set_snapshots(snapshots)

    def _refresh_failed(self, message: str) -> None:
        self.tray.showMessage("API Budget refresh failed", message, QSystemTrayIcon.Warning, 5000)

    def poll_runtime(self) -> None:
        if not self._runtime_busy:
            self._run_runtime("status")

    def _run_runtime(self, action: str) -> None:
        if self._runtime_busy:
            return
        self._runtime_busy = True
        self.popup.runtime_card.set_busy(action in {"start", "restart"})
        if action in {"start", "restart"}:
            self.popup.set_runtime_snapshot(RuntimeSnapshot("Starting", self.popup.runtime_card.tunnel_label.text()))
        worker = RuntimeWorker(self.runtime_manager, action)
        worker.signals.done.connect(self._runtime_done)
        worker.signals.failed.connect(self._runtime_failed)
        self.pool.start(worker)

    def _runtime_done(self, snapshot: RuntimeSnapshot) -> None:
        self._runtime_busy = False
        self.popup.runtime_card.set_busy(False)
        for title, message in runtime_transition_messages(self._runtime_snapshot, snapshot):
            self.tray.showMessage(title, message, QSystemTrayIcon.Information, 5000)
        self._runtime_snapshot = snapshot
        self.popup.set_runtime_snapshot(snapshot)

    def _runtime_failed(self, message: str) -> None:
        self._runtime_busy = False
        self.popup.runtime_card.set_busy(False)
        self.popup.runtime_card.backend_label.setText("Error / Unreachable")
        self.popup.runtime_card.backend_label.setToolTip(message)

    def open_runtime_logs(self) -> None:
        path = runtime_directory(self.config_dir)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_external_agents_folder(self) -> None:
        path = service_path(self.config) / ".local"
        if not path.is_dir():
            path = service_path(self.config)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def setup_tunnel_auth(self) -> None:
        if os.name != "nt":
            QMessageBox.information(self.popup, "Tunnel authentication", "Windows Credential Manager is available only on Windows.")
            return
        dialog = QDialog(self.popup)
        dialog.setWindowTitle("Set up tunnel authentication")
        dialog.setMinimumWidth(420)
        dialog.setStyleSheet(APP_STYLE)
        layout = QVBoxLayout(dialog)
        note = QLabel("Enter the Secure MCP Tunnel runtime key. It will be saved to Windows Credential Manager and passed to tunnel-client only when it starts.")
        note.setWordWrap(True)
        field = QLineEdit()
        field.setEchoMode(QLineEdit.Password)
        field.setPlaceholderText("Tunnel runtime key")
        layout.addWidget(note)
        layout.addWidget(field)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        save = QPushButton("Save securely")
        cancel.clicked.connect(dialog.reject)
        save.clicked.connect(dialog.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        if dialog.exec() != QDialog.Accepted:
            field.clear()
            dialog.deleteLater()
            return
        try:
            save_tunnel_credential(field.text())
        except (ValueError, RuntimeError):
            QMessageBox.warning(self.popup, "Tunnel authentication", "The credential could not be saved. Check the value and try again.")
        else:
            field.clear()
            if self.config.external_agents.enabled_on_startup:
                self._run_runtime("start")
            else:
                self.poll_runtime()
        finally:
            field.clear()
            dialog.deleteLater()

    def open_settings(self) -> None:
        self._tray_dismissed_at = None
        self.popup.hide()
        dialog = SettingsDialog(self.config, self.config_path)
        try:
            if dialog.exec() == QDialog.Accepted:
                self.config = dialog.config
                self.runtime_manager.config = self.config
                self._reset_timer()
                self.refresh()
                self.poll_runtime()
        finally:
            dialog.deleteLater()
