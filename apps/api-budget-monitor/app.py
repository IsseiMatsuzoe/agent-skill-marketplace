from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from api_budget_monitor.config import default_config_dir
from api_budget_monitor.ui import BudgetMonitorApp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Windows tray monitor for external-agent API budgets")
    parser.add_argument("--config-dir", type=Path, default=default_config_dir())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    app = QApplication(sys.argv)
    app.setApplicationName("API Budget")
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("System tray is not available on this desktop.", file=sys.stderr)
        return 2
    monitor = BudgetMonitorApp(app, args.config_dir)
    app._budget_monitor = monitor  # keep QObject graph alive for the application lifetime
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
