"""Ship to App — generates a ZIP with install.bat / uninstall.bat.

The ZIP contains pre-patched game files (PAZ + PAMT + PAPGT) ready to
copy into the game directory.  The BAT scripts auto-discover Steam,
backup originals, and copy patched files.  Uninstall uses Steam Verify.
"""

import os
import json
import zipfile
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QComboBox, QCheckBox, QPushButton,
    QFileDialog, QProgressBar, QMessageBox,
)
from PySide6.QtCore import Qt


GAME_LANGUAGES = [
    ("kor", "Korean"),
    ("eng", "English"),
    ("jpn", "Japanese"),
    ("rus", "Russian"),
    ("tur", "Turkish"),
    ("spa-es", "Spanish (Spain)"),
    ("spa-mx", "Spanish (Mexico)"),
    ("fre", "French"),
    ("ger", "German"),
    ("ita", "Italian"),
    ("pol", "Polish"),
    ("por-br", "Portuguese (Brazil)"),
    ("zho-tw", "Chinese (Traditional)"),
    ("zho-cn", "Chinese (Simplified)"),
]

LANG_TO_PALOC = {k: f"localizationstring_{k}.paloc" for k, _ in GAME_LANGUAGES}


class ShipToAppDialog(QDialog):
    """Dialog for generating a ZIP+BAT distribution package."""

    def __init__(self, project, vfs, discovered_palocs, config, parent=None):
        super().__init__(parent)
        self._project = project
        self._vfs = vfs
        self._discovered_palocs = discovered_palocs
        self._config = config
        self._built_font_data = None
        self._built_font_info = None
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Ship to App — Generate ZIP Package")
        self.setMinimumWidth(550)

        layout = QVBoxLayout(self)

        # --- Mod Info ---
        info_group = QGroupBox("Mod Information")
        info_form = QFormLayout(info_group)

        target_lang = self._project.target_lang or ""
        from translation.language_config import LanguageConfig
        lc = LanguageConfig()
        lang_obj = lc.get_language(target_lang)
        lang_name = lang_obj.name if lang_obj else target_lang

        self._mod_name = QLineEdit(f"Crimson Desert - {lang_name} Localization")
        self._mod_name.setToolTip("Name shown in the BAT window title.")
        info_form.addRow("Mod Name:", self._mod_name)

        self._translator = QLineEdit()
        self._translator.setPlaceholderText("Your name or team name")
        info_form.addRow("Translator:", self._translator)

        self._version = QLineEdit("1.0.0")
        info_form.addRow("Version:", self._version)

        layout.addWidget(info_group)

        # --- Game Language to Replace ---
        lang_group = QGroupBox("Game Language to Replace")
        lang_form = QFormLayout(lang_group)

        self._replace_combo = QComboBox()
        for key, name in GAME_LANGUAGES:
            self._replace_combo.addItem(f"{name} ({key})", key)
        eng_idx = self._replace_combo.findData("eng")
        if eng_idx >= 0:
            self._replace_combo.setCurrentIndex(eng_idx)
        self._replace_combo.setToolTip("End users select this language in-game to see your translation.")
        self._replace_combo.currentIndexChanged.connect(self._on_replace_changed)
        lang_form.addRow("Replace:", self._replace_combo)

        self._lang_warning = QLabel(
            f'End users will select "English" in-game to see {lang_name} text.'
        )
        self._lang_warning.setStyleSheet("color: #f9e2af; font-size: 11px;")
        self._lang_warning.setWordWrap(True)
        lang_form.addRow("", self._lang_warning)

        layout.addWidget(lang_group)

        # --- Font ---
        font_group = QGroupBox("Font (adds missing glyphs for target language)")
        font_form = QFormLayout(font_group)

        self._include_font = QCheckBox("Include custom font")
        self._include_font.setToolTip("Select a donor font to add missing glyphs for your language.")
        self._include_font.toggled.connect(self._on_font_toggled)
        font_form.addRow("", self._include_font)

        donor_row = QHBoxLayout()
        self._donor_path = QLineEdit()
        self._donor_path.setPlaceholderText("Select donor .ttf font...")
        self._donor_path.setEnabled(False)
        donor_row.addWidget(self._donor_path, 1)
        self._donor_btn = QPushButton("Browse...")
        self._donor_btn.setEnabled(False)
        self._donor_btn.clicked.connect(self._browse_donor)
        donor_row.addWidget(self._donor_btn)
        font_form.addRow("Donor Font:", donor_row)

        self._font_status = QLabel("Enable checkbox, then select a donor font.")
        self._font_status.setStyleSheet("color: #6c7086; font-size: 11px;")
        self._font_status.setWordWrap(True)
        font_form.addRow("Status:", self._font_status)

        layout.addWidget(font_group)

        # --- Progress ---
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._status = QLabel("")
        layout.addWidget(self._status)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        self._generate_btn = QPushButton("Generate ZIP")
        self._generate_btn.setObjectName("primary")
        self._generate_btn.clicked.connect(self._do_generate)
        btn_row.addWidget(self._generate_btn)
        layout.addLayout(btn_row)

    # ── Slots ────────────────────────────────────────────────────────

    def _on_replace_changed(self):
        lang_key = self._replace_combo.currentData()
        lang_name = dict(GAME_LANGUAGES).get(lang_key, lang_key)
        target = self._project.target_lang
        from translation.language_config import LanguageConfig
        tl = LanguageConfig().get_language(target)
        target_name = tl.name if tl else target
        self._lang_warning.setText(
            f'End users will select "{lang_name}" in-game to see {target_name} text.'
        )

    def _on_font_toggled(self, checked):
        self._donor_path.setEnabled(checked)
        self._donor_btn.setEnabled(checked)
        if not checked:
            self._built_font_data = None
            self._built_font_info = None
            self._font_status.setText("Font disabled.")
            self._font_status.setStyleSheet("color: #6c7086; font-size: 11px;")

    def _browse_donor(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Donor Font", "", "Font Files (*.ttf *.otf)")
        if not path:
            return
        self._donor_path.setText(path)
        self._build_font(path)

    def _build_font(self, donor_path):
        """Extract game base font + add glyphs from donor."""
        self._font_status.setText("Building font...")
        self._font_status.setStyleSheet("color: #89b4fa; font-size: 11px;")
        QApplication.processEvents()

        try:
            from core.font_builder import load_ttfont, save_ttfont, add_script_glyphs
            from core.script_ranges import LANG_TO_SCRIPT, SCRIPT_REGISTRY

            replace_key = self._replace_combo.currentData()
            target_font_name = f"basefont_{replace_key}.ttf"

            # Find the exact game font
            base_entry = None
            base_group = None
            for _g, pamt in self._vfs._pamt_cache.items():
                for entry in pamt.file_entries:
                    if entry.path.replace("\\", "/").lower().endswith(target_font_name):
                        base_entry = entry
                        base_group = _g
                        break
                if base_entry:
                    break

            # Fallback: generic basefont.ttf
            if not base_entry:
                for _g, pamt in self._vfs._pamt_cache.items():
                    for entry in pamt.file_entries:
                        if entry.path.replace("\\", "/").lower().endswith("basefont.ttf"):
                            base_entry = entry
                            base_group = _g
                            break
                    if base_entry:
                        break

            if not base_entry:
                self._font_status.setText("No game font found.")
                self._font_status.setStyleSheet("color: #f38ba8; font-size: 11px;")
                return

            base_bytes = self._vfs.read_entry_data(base_entry)
            script_name = LANG_TO_SCRIPT.get(self._project.target_lang, "Latin")

            target_font = load_ttfont(base_bytes)
            with open(donor_path, "rb") as f:
                donor_font = load_ttfont(f.read())

            if SCRIPT_REGISTRY.get(script_name):
                add_script_glyphs(target_font, donor_font, script_name)

            self._built_font_data = save_ttfont(target_font)
            self._built_font_info = {
                "group": base_group,
                "filename": os.path.basename(base_entry.path),
                "full_path": base_entry.path,
                "compression_type": base_entry.compression_type,
            }

            self._font_status.setText(
                f"Font ready: {os.path.basename(base_entry.path)} + "
                f"{os.path.basename(donor_path)} | Script: {script_name}"
            )
            self._font_status.setStyleSheet("color: #a6e3a1; font-size: 11px;")

        except Exception as e:
            self._font_status.setText(f"Font failed: {e}")
            self._font_status.setStyleSheet("color: #f38ba8; font-size: 11px;")
            self._built_font_data = None

    # ── Generate ─────────────────────────────────────────────────────

    def _do_generate(self):
        if not self._translator.text().strip():
            QMessageBox.warning(self, "Missing", "Enter translator name.")
            return

        default_name = self._mod_name.text().replace(" ", "_").replace("-", "_")
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save ZIP", os.path.expanduser(f"~/Desktop/{default_name}.zip"), "ZIP (*.zip)",
        )
        if not save_path:
            return

        self._generate_btn.setEnabled(False)
        self._progress.setVisible(True)

        try:
            self._build_zip(save_path)
            self._progress.setVisible(False)
            self._generate_btn.setEnabled(True)

            size = os.path.getsize(save_path)
            size_str = f"{size / (1024*1024):.1f} MB" if size > 1024*1024 else f"{size / 1024:.0f} KB"
            QMessageBox.information(
                self, "Done",
                f"ZIP saved to:\n{save_path}\n\nSize: {size_str}\n"
                f"Font: {'Included' if self._built_font_data else 'No'}\n\n"
                f"End user extracts ZIP and runs install.bat."
            )
            self.accept()
        except Exception as e:
            self._progress.setVisible(False)
            self._generate_btn.setEnabled(True)
            QMessageBox.critical(self, "Error", str(e))

    def _build_zip(self, output_path):
        from core.paloc_parser import parse_paloc, splice_values_in_raw
        from core.pamt_parser import (
            parse_pamt, find_file_entry, update_pamt_file_entry,
            update_pamt_paz_entry, update_pamt_self_crc,
        )
        from core.papgt_manager import (
            parse_papgt, get_pamt_crc_offset, update_papgt_pamt_crc,
            update_papgt_self_crc,
        )
        from core.compression_engine import compress
        from core.crypto_engine import encrypt
        from core.checksum_engine import pa_checksum

        game_path = self._config.get("general.last_game_path", "")
        replace_key = self._replace_combo.currentData()
        replace_name = dict(GAME_LANGUAGES).get(replace_key, replace_key)
        target_paloc = LANG_TO_PALOC.get(replace_key, "")

        from translation.language_config import LanguageConfig
        tl = LanguageConfig().get_language(self._project.target_lang)
        target_name = tl.name if tl else self._project.target_lang
        mod_name = self._mod_name.text().strip()
        translator = self._translator.text().strip()
        version = self._version.text().strip()

        # Find target paloc group
        target_group = ""
        for p in self._discovered_palocs:
            if p["filename"] == target_paloc:
                target_group = p["group"]
                break
        if not target_group:
            raise ValueError(f"Target paloc '{target_paloc}' not found in game")

        # ── Step 1: Read target paloc and splice translations ──
        self._status.setText("Reading target paloc...")
        self._progress.setValue(5)
        QApplication.processEvents()

        group_dir = os.path.join(game_path, target_group)
        pamt_data = parse_pamt(os.path.join(group_dir, "0.pamt"), paz_dir=group_dir)
        paloc_entry = find_file_entry(pamt_data, target_paloc)
        if not paloc_entry:
            raise FileNotFoundError(f"'{target_paloc}' not in PAMT")

        raw = self._vfs.read_entry_data(paloc_entry)
        target_entries = parse_paloc(raw)

        self._status.setText("Splicing translations...")
        self._progress.setValue(15)
        QApplication.processEvents()

        project_map = {e.key: e for e in self._project.entries}
        replacements = []
        for pe in target_entries:
            proj = project_map.get(pe.key)
            if proj and proj.translated_text:
                replacements.append((pe, proj.translated_text))
        translated_paloc = splice_values_in_raw(raw, replacements) if replacements else raw

        # ── Step 2: Compress + encrypt ──
        self._status.setText("Compressing & encrypting paloc...")
        self._progress.setValue(25)
        QApplication.processEvents()

        comp = compress(translated_paloc, 2)
        enc = encrypt(comp, os.path.basename(paloc_entry.path))

        # ── Step 3: Build patched PAZ ──
        self._status.setText("Building patched PAZ...")
        self._progress.setValue(35)
        QApplication.processEvents()

        with open(paloc_entry.paz_file, "rb") as f:
            paz = bytearray(f.read())
        aligned = (len(paz) + 15) & ~15
        if aligned > len(paz):
            paz.extend(b"\x00" * (aligned - len(paz)))
        new_offset = len(paz)
        paz.extend(enc)

        self._status.setText("Computing checksums...")
        self._progress.setValue(50)
        QApplication.processEvents()

        paz_crc = pa_checksum(bytes(paz))

        # ── Step 4: Update PAMT ──
        pamt_raw = bytearray(pamt_data.raw_data)
        update_pamt_file_entry(pamt_raw, paloc_entry,
                               new_comp_size=len(enc),
                               new_orig_size=len(translated_paloc),
                               new_offset=new_offset)
        update_pamt_paz_entry(pamt_raw, pamt_data.paz_table[paloc_entry.paz_index],
                              paz_crc, len(paz))
        update_pamt_self_crc(pamt_raw)

        # ── Step 5: Update PAPGT ──
        papgt_path = os.path.join(game_path, "meta", "0.papgt")
        papgt_data = parse_papgt(papgt_path)
        papgt_raw = bytearray(papgt_data.raw_data)
        pamt_crc = pa_checksum(bytes(pamt_raw[12:]))
        crc_off = get_pamt_crc_offset(papgt_data, int(target_group))
        if crc_off is not None:
            update_papgt_pamt_crc(papgt_raw, crc_off, pamt_crc)
        update_papgt_self_crc(papgt_raw)

        # Collect patched files
        paz_basename = os.path.basename(paloc_entry.paz_file)
        patched = {
            f"{target_group}/0.pamt": bytes(pamt_raw),
            f"{target_group}/{paz_basename}": bytes(paz),
            "meta/0.papgt": bytes(papgt_raw),
        }
        backup_files = list(patched.keys())

        # ── Step 6: Font (optional) ──
        if self._built_font_data and self._built_font_info:
            self._status.setText("Patching font...")
            self._progress.setValue(65)
            QApplication.processEvents()

            fi = self._built_font_info
            fg = fi["group"]
            fg_dir = os.path.join(game_path, fg)
            fg_pamt = parse_pamt(os.path.join(fg_dir, "0.pamt"), paz_dir=fg_dir)
            fentry = find_file_entry(fg_pamt, fi["full_path"])
            if fentry:
                fcomp = compress(self._built_font_data, 2)
                with open(fentry.paz_file, "rb") as f:
                    fpaz = bytearray(f.read())
                fa = (len(fpaz) + 15) & ~15
                if fa > len(fpaz):
                    fpaz.extend(b"\x00" * (fa - len(fpaz)))
                foff = len(fpaz)
                fpaz.extend(fcomp)
                fcrc = pa_checksum(bytes(fpaz))

                fr = bytearray(fg_pamt.raw_data)
                update_pamt_file_entry(fr, fentry,
                                       new_comp_size=len(fcomp),
                                       new_orig_size=len(self._built_font_data),
                                       new_offset=foff)
                update_pamt_paz_entry(fr, fg_pamt.paz_table[fentry.paz_index], fcrc, len(fpaz))
                update_pamt_self_crc(fr)

                fcrc2 = pa_checksum(bytes(fr[12:]))
                fco = get_pamt_crc_offset(papgt_data, int(fg))
                if fco is not None:
                    update_papgt_pamt_crc(papgt_raw, fco, fcrc2)
                update_papgt_self_crc(papgt_raw)

                fbas = os.path.basename(fentry.paz_file)
                patched[f"{fg}/0.pamt"] = bytes(fr)
                patched[f"{fg}/{fbas}"] = bytes(fpaz)
                patched["meta/0.papgt"] = bytes(papgt_raw)
                backup_files.append(f"{fg}/0.pamt")
                backup_files.append(f"{fg}/{fbas}")

        # ── Step 7: Write ZIP ──
        self._status.setText("Writing ZIP...")
        self._progress.setValue(85)
        QApplication.processEvents()

        install_bat = self._bat_install(mod_name, translator, version,
                                        replace_name, target_name,
                                        list(patched.keys()), backup_files)
        uninstall_bat = self._bat_uninstall(mod_name, replace_name)
        readme = self._readme(mod_name, translator, version,
                              replace_name, target_name, len(replacements))

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for rel, data in patched.items():
                zf.writestr(f"data/{rel}", data)
            zf.writestr("install.bat", install_bat)
            zf.writestr("uninstall.bat", uninstall_bat)
            zf.writestr("README.txt", readme)

        self._status.setText("Done!")
        self._progress.setValue(100)

    # ── BAT generators ───────────────────────────────────────────────

    def _bat_install(self, mod_name, translator, version,
                     replace_name, target_name, files, backup_files):
        L = [
            '@echo off',
            'setlocal EnableDelayedExpansion',
            'chcp 65001 >nul 2>&1',
            f'title {mod_name} v{version}',
            'echo.',
            f'echo  {mod_name}',
            f'echo  by {translator} - v{version}',
            f'echo  Replaces: {replace_name} with {target_name}',
            'echo.',
            '',
            'set "GP="',
            'for %%D in (',
            '    "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Crimson Desert"',
            '    "C:\\Program Files\\Steam\\steamapps\\common\\Crimson Desert"',
            '    "D:\\SteamLibrary\\steamapps\\common\\Crimson Desert"',
            '    "E:\\SteamLibrary\\steamapps\\common\\Crimson Desert"',
            '    "F:\\SteamLibrary\\steamapps\\common\\Crimson Desert"',
            ') do ( if exist "%%~D\\meta\\0.papgt" ( set "GP=%%~D" & goto :f ) )',
            'for /f "tokens=2*" %%A in (\'reg query "HKCU\\Software\\Valve\\Steam" /v SteamPath 2^>nul\') do set "SP=%%B"',
            'if defined SP if exist "!SP!\\steamapps\\common\\Crimson Desert\\meta\\0.papgt" set "GP=!SP!\\steamapps\\common\\Crimson Desert"',
            'if not defined GP ( echo [ERROR] Game not found. & pause & exit /b 1 )',
            ':f',
            'echo [OK] !GP!',
            'echo.',
            'set "D=%~dp0data"',
        ]
        for f in sorted(set(files)):
            s = f.replace("/", "\\")
            L.append(f'copy /Y "!D!\\{s}" "!GP!\\{s}" >nul && echo   Copied: {s}')
        L += [
            'echo.',
            f'echo [DONE] {target_name} installed!',
            f'echo In-game: select "{replace_name}" to see {target_name}.',
            'echo To uninstall: run uninstall.bat',
            'echo.',
            'pause',
        ]
        return "\r\n".join(L)

    def _bat_uninstall(self, mod_name, replace_name):
        return "\r\n".join([
            '@echo off',
            'setlocal EnableDelayedExpansion',
            'chcp 65001 >nul 2>&1',
            f'title Uninstall {mod_name}',
            'echo.',
            f'echo  Uninstall {mod_name}',
            'echo  Steam will verify and restore original files.',
            'echo.',
            'set /p C="Proceed? (Y/N): "',
            'if /i not "!C!"=="Y" exit /b 0',
            'set "GP="',
            'for %%D in (',
            '    "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Crimson Desert"',
            '    "C:\\Program Files\\Steam\\steamapps\\common\\Crimson Desert"',
            '    "D:\\SteamLibrary\\steamapps\\common\\Crimson Desert"',
            ') do ( if exist "%%~D\\meta\\0.papgt" set "GP=%%~D" )',
            'if defined GP if exist "!GP!\\crimsonforge_mods" rmdir /s /q "!GP!\\crimsonforge_mods" 2>nul',
            'start steam://validate/3321460',
            f'echo [OK] Steam will restore {replace_name}. Wait for it to finish.',
            'echo.',
            'pause',
        ])

    def _readme(self, mod_name, translator, version, replace_name, target_name, count):
        return (
            f"{mod_name}\n{'=' * len(mod_name)}\n\n"
            f"Translator: {translator}\nVersion: {version}\n"
            f"Translated: {count:,} entries\n\n"
            f"INSTALL:\n  1. Extract ZIP\n  2. Run install.bat\n"
            f'  3. In-game select "{replace_name}" to see {target_name}\n\n'
            f"UNINSTALL:\n  Run uninstall.bat (uses Steam Verify)\n\n"
            f"Generated by CrimsonForge\nhttps://github.com/hzeemr/crimsonforge\n"
        )
