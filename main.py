"""CrimsonForge - Crimson Desert Modding Studio."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

from version import APP_VERSION, APP_NAME
from utils.config import ConfigManager, ConfigLoadError
from utils.logger import setup_logger, get_logger
from ai.provider_registry import ProviderRegistry
from ui.main_window import MainWindow


def _close_splash():
    """Close the PyInstaller splash screen if running from a bundled exe."""
    try:
        import pyi_splash          # only available inside PyInstaller bundle
        pyi_splash.close()
    except ImportError:
        pass


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("hzeem")

    # Set a multilingual font with fallbacks for Korean, Chinese, Japanese, Arabic, etc.
    from PySide6.QtGui import QFont
    font = QFont("Segoe UI", 10)
    font.setFamilies([
        "Segoe UI",            # Latin, Cyrillic
        "Microsoft YaHei",     # Chinese (Simplified)
        "Malgun Gothic",       # Korean
        "Meiryo",              # Japanese
        "Segoe UI Symbol",     # Symbols, emoji
        "Noto Sans",           # Broad Unicode coverage (if installed)
    ])
    app.setFont(font)

    try:
        config = ConfigManager()
    except ConfigLoadError as e:
        _close_splash()
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Configuration Error", str(e))
        return 1

    logger = setup_logger(
        log_level=config.get("advanced.log_level", "INFO"),
        log_file=config.get("advanced.log_file", ""),
        debug_mode=config.get("advanced.debug_mode", False),
    )
    logger.info("%s v%s starting...", APP_NAME, APP_VERSION)
    logger.info("Config loaded from: %s", config.config_path)

    registry = ProviderRegistry()
    registry.initialize_from_config(config.get_section("ai_providers"))
    logger.info("AI providers initialized: %s", registry.list_enabled_provider_ids())
    window = MainWindow(config, registry)

    _close_splash()
    window.show()

    logger.info("Application ready")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
