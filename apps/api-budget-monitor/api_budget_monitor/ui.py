from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QColor, QCursor, QDesktopServices, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
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


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, config_path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config
        self.config_path = config_path
        self.setWindowTitle("API Budget settings")
        self.setMinimumWidth(360)
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
        note = QLabel("Secrets and key rotation dates stay in the local config folder; keys are never displayed here.")
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
        for provider_id, widget in self.budget_inputs.items():
            self.config.providers[provider_id]["reference_budget_usd"] = widget.value()
            until = self.until_inputs[provider_id].text().strip()
            self.config.providers[provider_id]["key_valid_until"] = until or None
        manual = self.manual_inputs["anthropic"].value()
        self.config.providers["anthropic"]["manual_remaining_usd"] = None if manual < 0 else manual
        save_config(self.config_path, self.config)
        self.accept()


class BudgetPopup(QWidget):
    request_refresh = Signal()
    request_settings = Signal()

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
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
        self.show()
        self.raise_()
        self.activateWindow()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self.hide()
        super().focusOutEvent(event)


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
        self.pool = QThreadPool.globalInstance()
        self.popup = BudgetPopup()
        self.popup.request_refresh.connect(self.refresh)
        self.popup.request_settings.connect(self.open_settings)

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

    def _reset_timer(self) -> None:
        self.timer.start(max(1, self.config.refresh_minutes) * 60 * 1000)

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_popup()

    def toggle_popup(self) -> None:
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

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.config, self.config_path, self.popup)
        if dialog.exec() == QDialog.Accepted:
            self.config = dialog.config
            self._reset_timer()
            self.refresh()
