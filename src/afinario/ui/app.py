import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from afinario.config import Settings
from afinario.logging_config import configure_logging
from afinario.ui.window import MainWindow

STYLE = """
QMainWindow { background: #151b24; }
QWidget { background-color: #151b24; color: #e5eaf1; font-size: 13px; }
QLabel#brand { font-size: 30px; font-weight: 700; color: #76ddc7; }
QLabel#subtitle { color: #a8b4c4; }
QListWidget, QTableView, QTextEdit, QLineEdit {
    background: #1c2531; color: #e5eaf1; border: 1px solid #394757;
    border-radius: 5px; selection-background-color: #315d65;
}
QTableView { alternate-background-color: #202c39; gridline-color: #303e4d; }
QHeaderView::section { background: #263342; color: #dce6f1; padding: 7px; border: 0; }
QPushButton { background: #2b3949; border: 1px solid #455b70;
    border-radius: 5px; padding: 9px; }
QPushButton:hover { background: #385065; }
QPushButton:disabled { color: #788591; background: #232c36; }
QPushButton#primary { background: #267766; border: 1px solid #61c9ad; }
QPushButton#primary:disabled { background: #253c38; color: #839f97; }
QPushButton:focus, QLineEdit:focus, QListWidget:focus, QTableView:focus {
    border: 2px solid #76ddc7;
}
QLineEdit { padding: 9px; }
QTabBar::tab { background: #263342; padding: 8px 14px; }
QTabBar::tab:selected { background: #315d65; }
QProgressBar { background: #263342; border: 0; }
QProgressBar::chunk { background: #76ddc7; }
QCheckBox { spacing: 5px; }
"""


def main(argv: list[str] | None = None, *, settings: Settings | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description="Afinário desktop")
    parser.add_argument("folders", nargs="*", type=Path)
    parser.add_argument("--config", type=Path)
    parsed = parser.parse_args(args)
    if settings is None:
        config = parsed.config or (
            Path("afinario.local.toml") if Path("afinario.local.toml").is_file() else None
        )
        try:
            settings = Settings.load(config)
        except (OSError, ValueError):
            parser.error("Não foi possível carregar a configuração de reconhecimento.")
    configure_logging(settings.acoustid_key, settings.audd_token)
    app = QApplication.instance() or QApplication(["Afinário"])
    app.setApplicationName("Afinário")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = MainWindow(settings)
    # Optional positional folders make launching a chosen library straightforward.
    for value in parsed.folders:
        window.add_folder(value)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
