"""Settings tab - configure AI providers, paths, themes, and translation options."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QCheckBox, QGroupBox, QSpinBox, QTextEdit, QScrollArea,
    QSplitter, QListWidget, QStackedWidget, QFormLayout,
)
from PySide6.QtCore import Qt, Signal

from ai.provider_registry import ProviderRegistry, PROVIDER_CLASSES
from ai.model_loader import ModelLoader
from ui.dialogs.confirmation import show_error, show_info
from utils.logger import get_logger

logger = get_logger("ui.tab_settings")


class SettingsTab(QWidget):
    """Settings panel with category sidebar and configuration forms."""

    settings_changed = Signal()
    theme_changed = Signal(str)

    def __init__(self, config, registry: ProviderRegistry, parent=None):
        super().__init__(parent)
        self._config = config
        self._registry = registry
        self._model_loader = ModelLoader(registry)
        self._provider_widgets: dict[str, dict] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)

        self._category_list = QListWidget()
        self._category_list.setFixedWidth(160)
        self._category_list.addItems(["General", "AI Providers", "Translation", "Repack", "Advanced"])
        self._category_list.currentRowChanged.connect(self._on_category_changed)
        layout.addWidget(self._category_list)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)

        self._stack.addWidget(self._build_general_page())
        self._stack.addWidget(self._build_ai_page())
        self._stack.addWidget(self._build_translation_page())
        self._stack.addWidget(self._build_repack_page())
        self._stack.addWidget(self._build_advanced_page())

        self._category_list.setCurrentRow(0)

    def _on_category_changed(self, row: int):
        self._stack.setCurrentIndex(row)

    def _build_general_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self._theme_combo = QComboBox()
        self._theme_combo.setToolTip("Switch between dark (Catppuccin Mocha) and light (Catppuccin Latte) UI themes.")
        self._theme_combo.addItems(["dark", "light"])
        self._theme_combo.setCurrentText(self._config.get("general.theme", "dark"))
        self._theme_combo.currentTextChanged.connect(lambda t: self.theme_changed.emit(t))
        form.addRow("Theme:", self._theme_combo)

        self._game_path_input = QLineEdit(self._config.get("general.last_game_path", ""))
        self._game_path_input.setToolTip("Default path to the Crimson Desert game packages directory.\nUsed by 'Load Game' on the main screen.")
        form.addRow("Default Game Path:", self._game_path_input)

        self._output_path_input = QLineEdit(self._config.get("general.last_output_path", ""))
        self._output_path_input.setToolTip("Default directory for extracted and exported files.")
        form.addRow("Default Output Path:", self._output_path_input)

        return page

    def _build_ai_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        main_layout = QVBoxLayout(container)

        for provider_id in PROVIDER_CLASSES:
            group = QGroupBox(PROVIDER_CLASSES[provider_id].name)
            form = QFormLayout(group)

            enabled_cb = QCheckBox()
            enabled_cb.setToolTip("Enable or disable this AI provider for translation.")
            enabled_cb.setChecked(self._config.get(f"ai_providers.{provider_id}.enabled", False))
            form.addRow("Enabled:", enabled_cb)

            api_key_input = QLineEdit(self._config.get(f"ai_providers.{provider_id}.api_key", ""))
            api_key_input.setEchoMode(QLineEdit.Password)
            api_key_input.setToolTip("Your API key for this provider. Stored locally and never shared.")
            form.addRow("API Key:", api_key_input)

            base_url_input = QLineEdit(self._config.get(f"ai_providers.{provider_id}.base_url", ""))
            base_url_input.setToolTip("Custom API endpoint URL. Leave empty to use the provider's default.\nUseful for self-hosted models (Ollama, vLLM) or proxy servers.")
            form.addRow("Base URL:", base_url_input)

            model_combo = QComboBox()
            model_combo.setEditable(True)
            model_combo.setToolTip("The AI model to use for translations. Click 'Load Models' to fetch the available list.\nYou can also type a model name manually.")
            model_combo.setCurrentText(self._config.get(f"ai_providers.{provider_id}.default_model", ""))
            form.addRow("Default Model:", model_combo)

            test_btn = QPushButton("Test Connection")
            test_btn.setToolTip("Test the API connection and verify your API key works.")
            test_result = QLabel("")
            test_result.setToolTip("Shows the result of the connection test.")
            test_row = QHBoxLayout()
            test_row.addWidget(test_btn)
            test_row.addWidget(test_result, 1)
            form.addRow("", test_row)

            load_models_btn = QPushButton("Load Models")
            load_models_btn.setToolTip("Fetch the list of available models from this provider's API.\nPopulates the model dropdown above.")
            form.addRow("", load_models_btn)

            self._provider_widgets[provider_id] = {
                "enabled": enabled_cb,
                "api_key": api_key_input,
                "base_url": base_url_input,
                "model": model_combo,
                "test_result": test_result,
            }

            def make_test_handler(pid, result_label):
                def handler():
                    self._apply_provider_config(pid)
                    try:
                        provider = self._registry.get_provider(pid)
                        conn = provider.test_connection()
                        if conn.connected:
                            result_label.setText(f"Connected ({conn.models_available} models)")
                            result_label.setStyleSheet("color: #a6e3a1;")
                        else:
                            result_label.setText(f"Failed: {conn.error}")
                            result_label.setStyleSheet("color: #f38ba8;")
                    except Exception as e:
                        result_label.setText(f"Error: {e}")
                        result_label.setStyleSheet("color: #f38ba8;")
                return handler

            def make_load_handler(pid, combo):
                def handler():
                    self._apply_provider_config(pid)
                    try:
                        models = self._model_loader.load_models(pid, force_refresh=True)
                        combo.clear()
                        for m in models:
                            combo.addItem(m.name, m.model_id)
                    except Exception as e:
                        show_error(self, "Error", f"Failed to load models: {e}")
                return handler

            test_btn.clicked.connect(make_test_handler(provider_id, test_result))
            load_models_btn.clicked.connect(make_load_handler(provider_id, model_combo))

            main_layout.addWidget(group)

        save_btn = QPushButton("Save Settings")
        save_btn.setObjectName("primary")
        save_btn.setToolTip("Save all AI provider settings to the configuration file.")
        save_btn.clicked.connect(self._save_settings)
        main_layout.addWidget(save_btn)

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setObjectName("danger")
        reset_btn.setToolTip("Reset all settings to factory defaults. This cannot be undone.")
        reset_btn.clicked.connect(self._reset_defaults)
        main_layout.addWidget(reset_btn)

        main_layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def _build_translation_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self._autosave_check = QCheckBox()
        self._autosave_check.setToolTip("Automatically save translation progress at regular intervals.\nPrevents data loss if the app crashes.")
        self._autosave_check.setChecked(self._config.get("translation.autosave_enabled", True))
        form.addRow("Autosave Enabled:", self._autosave_check)

        self._autosave_interval = QSpinBox()
        self._autosave_interval.setToolTip("How often to auto-save (in seconds). Lower = safer but more disk writes.")
        self._autosave_interval.setRange(5, 600)
        self._autosave_interval.setValue(self._config.get("translation.autosave_interval_seconds", 30))
        self._autosave_interval.setSuffix(" seconds")
        form.addRow("Autosave Interval:", self._autosave_interval)

        self._batch_size = QSpinBox()
        self._batch_size.setToolTip("Number of strings sent to the AI in each batch request.\nLarger = faster but uses more tokens per request. Recommended: 5-20.")
        self._batch_size.setRange(1, 100)
        self._batch_size.setValue(self._config.get("translation.batch_size", 10))
        form.addRow("Batch Size:", self._batch_size)

        self._batch_delay = QSpinBox()
        self._batch_delay.setToolTip("Delay between batch requests (in milliseconds).\nPrevents rate limiting from AI providers. 500ms is usually safe.")
        self._batch_delay.setRange(0, 10000)
        self._batch_delay.setValue(self._config.get("translation.batch_delay_ms", 500))
        self._batch_delay.setSuffix(" ms")
        form.addRow("Batch Delay:", self._batch_delay)

        self._system_prompt = QTextEdit()
        self._system_prompt.setToolTip(
            "System prompt sent to the AI with every translation request.\n"
            "Leave EMPTY to use the built-in enterprise prompt (recommended).\n"
            "The built-in prompt handles: formatting tags, placeholders, proper nouns,\n"
            "game terminology, register matching, and glossary injection.\n\n"
            "Use {source_lang} and {target_lang} as placeholders for language names.\n"
            "Glossary terms from the Glossary Editor are automatically appended."
        )
        saved_prompt = self._config.get("translation.system_prompt", "")
        self._system_prompt.setPlainText(saved_prompt)
        self._system_prompt.setPlaceholderText(
            "Leave empty for built-in enterprise prompt (handles tags, placeholders, glossary, tone, etc.)"
        )
        self._system_prompt.setMaximumHeight(120)
        form.addRow("System Prompt:", self._system_prompt)

        self._user_prompt = QLineEdit(self._config.get("translation.user_prompt_template", ""))
        self._user_prompt.setToolTip(
            "Template for the user message sent with each batch.\n"
            "Use {text} as placeholder for the text to translate.\n"
            "Leave empty for default: just the raw text (recommended)."
        )
        self._user_prompt.setPlaceholderText("Leave empty for default (just sends the text)")
        form.addRow("User Prompt:", self._user_prompt)

        return page

    def _build_repack_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self._auto_backup_check = QCheckBox()
        self._auto_backup_check.setToolTip("Automatically create a backup of game files before repacking.\nHighly recommended — allows restoring the original game state.")
        self._auto_backup_check.setChecked(self._config.get("repack.auto_backup", True))
        form.addRow("Auto Backup:", self._auto_backup_check)

        self._verify_check = QCheckBox()
        self._verify_check.setToolTip("Verify the repacked files after writing.\nChecks that all checksums match and the archive is valid.")
        self._verify_check.setChecked(self._config.get("repack.verify_after_repack", True))
        form.addRow("Verify After Repack:", self._verify_check)

        self._preserve_ts_check = QCheckBox()
        self._preserve_ts_check.setToolTip("Keep original file modification timestamps when repacking.\nSome anti-cheat systems check timestamps.")
        self._preserve_ts_check.setChecked(self._config.get("repack.preserve_timestamps", True))
        form.addRow("Preserve Timestamps:", self._preserve_ts_check)

        self._backup_dir_input = QLineEdit(self._config.get("repack.backup_dir", ""))
        self._backup_dir_input.setToolTip("Directory where game file backups are stored.\nLeave empty to use the default location (~/.crimsonforge/backups/).")
        form.addRow("Backup Directory:", self._backup_dir_input)

        return page

    def _build_advanced_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self._log_level_combo = QComboBox()
        self._log_level_combo.setToolTip("Minimum log level to record.\nDEBUG = everything, INFO = normal, WARNING = issues only, ERROR = critical only.")
        self._log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self._log_level_combo.setCurrentText(self._config.get("advanced.log_level", "INFO"))
        form.addRow("Log Level:", self._log_level_combo)

        self._log_file_input = QLineEdit(self._config.get("advanced.log_file", ""))
        self._log_file_input.setToolTip("Path to the log file. Leave empty for console-only logging.")
        form.addRow("Log File:", self._log_file_input)

        self._debug_check = QCheckBox()
        self._debug_check.setToolTip("Enable debug mode for extra logging and diagnostic information.\nUseful for troubleshooting issues.")
        self._debug_check.setChecked(self._config.get("advanced.debug_mode", False))
        form.addRow("Debug Mode:", self._debug_check)

        return page

    def _apply_provider_config(self, provider_id: str):
        widgets = self._provider_widgets.get(provider_id, {})
        if not widgets:
            return
        self._config.set(f"ai_providers.{provider_id}.enabled", widgets["enabled"].isChecked())
        self._config.set(f"ai_providers.{provider_id}.api_key", widgets["api_key"].text())
        self._config.set(f"ai_providers.{provider_id}.base_url", widgets["base_url"].text())
        self._config.set(f"ai_providers.{provider_id}.default_model", widgets["model"].currentText())
        self._registry.initialize_from_config(self._config.get_section("ai_providers"))

    def _save_settings(self):
        self._config.set("general.theme", self._theme_combo.currentText())
        self._config.set("general.last_game_path", self._game_path_input.text())
        self._config.set("general.last_output_path", self._output_path_input.text())

        for pid, widgets in self._provider_widgets.items():
            self._config.set(f"ai_providers.{pid}.enabled", widgets["enabled"].isChecked())
            self._config.set(f"ai_providers.{pid}.api_key", widgets["api_key"].text())
            self._config.set(f"ai_providers.{pid}.base_url", widgets["base_url"].text())
            self._config.set(f"ai_providers.{pid}.default_model", widgets["model"].currentText())

        self._config.set("translation.autosave_enabled", self._autosave_check.isChecked())
        self._config.set("translation.autosave_interval_seconds", self._autosave_interval.value())
        self._config.set("translation.batch_size", self._batch_size.value())
        self._config.set("translation.batch_delay_ms", self._batch_delay.value())
        self._config.set("translation.system_prompt", self._system_prompt.toPlainText())
        self._config.set("translation.user_prompt_template", self._user_prompt.text())

        self._config.set("repack.auto_backup", self._auto_backup_check.isChecked())
        self._config.set("repack.verify_after_repack", self._verify_check.isChecked())
        self._config.set("repack.preserve_timestamps", self._preserve_ts_check.isChecked())
        self._config.set("repack.backup_dir", self._backup_dir_input.text())

        self._config.set("advanced.log_level", self._log_level_combo.currentText())
        self._config.set("advanced.log_file", self._log_file_input.text())
        self._config.set("advanced.debug_mode", self._debug_check.isChecked())

        self._config.save()
        self._registry.initialize_from_config(self._config.get_section("ai_providers"))
        self.settings_changed.emit()
        show_info(self, "Settings Saved", "All settings have been saved.")

    def _reset_defaults(self):
        self._config.reset_to_defaults()
        self._config.save()
        show_info(self, "Reset", "Settings reset to defaults. Restart the application to apply.")
