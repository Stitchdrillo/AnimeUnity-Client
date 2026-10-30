import os
import shutil
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QFileDialog, QMessageBox, QFormLayout,
    QCheckBox
    )

class SettingsTab(QWidget):
    def __init__(self, config_manager, db_manager):
        super().__init__()
        self.config_manager = config_manager
        self.db_manager = db_manager
        self.setup_ui()
        self.load_current_settings()

    def setup_ui(self):
        layout = QVBoxLayout()
        form_layout = QFormLayout()

        dir_layout = QHBoxLayout()
        self.dir_input = QLineEdit()
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse_directory)
        
        dir_layout.addWidget(self.dir_input)
        dir_layout.addWidget(self.browse_btn)
        form_layout.addRow("Download Directory:", dir_layout)

        self.workers_spinbox = QSpinBox()
        self.workers_spinbox.setRange(1, 16)
        self.workers_spinbox.setToolTip("Number of simultaneous video downloads.")
        form_layout.addRow("Max Concurrent Downloads:", self.workers_spinbox)

        self.chunk_spinbox = QSpinBox()
        self.chunk_spinbox.setRange(256, 10240)
        self.chunk_spinbox.setSingleStep(256)
        self.chunk_spinbox.setSuffix(" KB")
        form_layout.addRow("Download Chunk Size:", self.chunk_spinbox)
        
        self.domain_input = QLineEdit()
        self.domain_input.setPlaceholderText("https://www.animeunity.??")
        form_layout.addRow("Base Domain URL:", self.domain_input)
        
        self.auto_dl_check = QCheckBox("Automatically queue the next episode when watching")
        form_layout.addRow("Playback:", self.auto_dl_check)
        
        self.auto_del_check = QCheckBox("Delete current episode when clicking 'Next Episode'")
        form_layout.addRow("Storage:", self.auto_del_check)

        layout.addLayout(form_layout)

        self.save_btn = QPushButton("Save Settings")
        self.save_btn.clicked.connect(self.save_settings)
        layout.addWidget(self.save_btn)
        
        layout.addSpacing(30)
        
        self.purge_btn = QPushButton("Purge All Data (Videos, Covers, Database)")
        self.purge_btn.setStyleSheet("color: white; background-color: #d9534f; font-weight: bold; padding: 8px;")
        self.purge_btn.clicked.connect(self.purge_data)
        layout.addWidget(self.purge_btn)
        
        layout.addStretch()
        self.setLayout(layout)

    def browse_directory(self):
        current_dir = self.dir_input.text()
        if not os.path.exists(current_dir):
            current_dir = os.path.expanduser("~")
            
        dir_path = QFileDialog.getExistingDirectory(
            self, 
            "Select Download Directory", 
            current_dir
        )
        if dir_path:
            self.dir_input.setText(dir_path)

    def load_current_settings(self):
        self.dir_input.setText(self.config_manager.get("download_directory", ""))
        self.workers_spinbox.setValue(self.config_manager.get("max_concurrent_downloads", 4))
        self.chunk_spinbox.setValue(self.config_manager.get("chunk_size_kb", 1024))
        self.domain_input.setText(self.config_manager.get("base_domain", ""))
        self.auto_dl_check.setChecked(self.config_manager.get("auto_download_next", False))
        self.auto_del_check.setChecked(self.config_manager.get("auto_delete_seen", False))

    def save_settings(self):
        self.config_manager.set("download_directory", self.dir_input.text())
        self.config_manager.set("max_concurrent_downloads", self.workers_spinbox.value())
        self.config_manager.set("chunk_size_kb", self.chunk_spinbox.value())
        self.config_manager.set("base_domain", self.domain_input.text().rstrip('/'))
        self.config_manager.set("auto_download_next", self.auto_dl_check.isChecked())
        self.config_manager.set("auto_delete_seen", self.auto_del_check.isChecked())
        
        QMessageBox.information(self, "Settings Saved", "Your configuration has been updated successfully.")

    def purge_data(self):
        reply = QMessageBox.question(self, 'Confirm Purge', 
            'This will permanently delete ALL downloaded videos, cover images, and your library database. The app will close. Continue?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            
        if reply == QMessageBox.StandardButton.Yes:
            self.db_manager.close()
            
            if os.path.exists(self.db_manager.db_path):
                try:
                    os.remove(self.db_manager.db_path)
                except:
                    pass
            
            covers_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "covers"))
            if os.path.exists(covers_dir):
                shutil.rmtree(covers_dir, ignore_errors=True)
            
            dl_dir = self.config_manager.get("download_directory")
            if os.path.exists(dl_dir):
                shutil.rmtree(dl_dir, ignore_errors=True)
                os.makedirs(dl_dir, exist_ok=True)
            
            QMessageBox.information(self, "Purge Complete", "Data purged. The application will now close.")
            os._exit(0)
