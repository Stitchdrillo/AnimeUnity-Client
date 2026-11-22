"""Application entry point for the Anime Library Client."""

import sys
from PyQt6.QtWidgets import QApplication
from core.config_manager import ConfigManager
from core.database import DatabaseManager
from gui.main_window import MainWindow


def main() -> None:
    """Initialize core managers and launch the main application window."""
    app = QApplication(sys.argv)

    config_manager = ConfigManager()
    db_manager = DatabaseManager()

    window = MainWindow(config_manager, db_manager)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
