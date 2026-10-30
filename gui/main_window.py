import sys
import os
from PyQt6.QtWidgets import QMainWindow, QTabWidget, QWidget, QVBoxLayout, QLabel
from gui.settings_tab import SettingsTab
from gui.download_tab import DownloadTab
from gui.library_tab import LibraryTab
from gui.console_tab import ConsoleTab, StreamRedirector

class MainWindow(QMainWindow):
    def __init__(self, config_manager, db_manager):
        super().__init__()
        self.config_manager = config_manager
        self.db_manager = db_manager
        self.setWindowTitle("Anime Library Client")
        self.resize(1024, 768)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.library_tab = LibraryTab(self.db_manager, self.config_manager) 
        self.downloads_tab = DownloadTab(self.config_manager, self.db_manager) 
        self.settings_tab = SettingsTab(self.config_manager, self.db_manager)
        self.console_tab = ConsoleTab()

        self.library_tab.episode_download_requested.connect(self.downloads_tab.add_to_queue)
        self.downloads_tab.episode_downloaded_signal.connect(self.library_tab.on_episode_downloaded)
        self.downloads_tab.episode_download_cancelled_signal.connect(self.library_tab.on_episode_download_cancelled)

        self.tabs.addTab(self.library_tab, "Library")
        self.tabs.addTab(self.downloads_tab, "Downloads")
        self.tabs.addTab(self.settings_tab, "Settings")
        self.tabs.addTab(self.console_tab, "Console")
        
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        
        self.stream_redirector = StreamRedirector()
        self.stream_redirector.text_written.connect(self.console_tab.append_text)
        
        sys.stdout = self.stream_redirector
        sys.stderr = self.stream_redirector
        
        print("Application initialized. Console redirection active.")

    def closeEvent(self, event):
        """Intercepts the window close action to clean up background processes and db locks."""
        print("Shutting down...")
        
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr
        
        self.db_manager.close()
        event.accept()
        
        os._exit(0)
