"""Multi-format file preview pane.

Displays:
- Images: PNG, JPG, BMP, TGA, DDS, WebP, GIF (scaled to fit)
- Audio: WAV, OGG, MP3 with play/pause/stop/seek/volume/loop controls
- Audio: WEM, BNK (Wwise) with auto-install vgmstream transcoding
- Video: MP4, WebM, AVI with full player controls
- HTML/THTML: Real rendered preview via QWebEngineView
- CSS: Rendered preview (wrapped in HTML) via QWebEngineView
- Fonts: TTF/OTF sample text preview with loaded font
- Text: Syntax-highlighted read-only view (XML, JSON, paloc, plain)
- Binary: Hex viewer with ASCII sidebar
"""

import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QStackedWidget,
    QPlainTextEdit, QScrollArea, QPushButton,
)
from PySide6.QtGui import QPixmap, QFont
from PySide6.QtCore import Qt, QUrl

from core.file_detector import detect_file_type
from ui.widgets.audio_player import AudioPlayerWidget
from utils.platform_utils import format_file_size

IDX_EMPTY = 0
IDX_IMAGE = 1
IDX_TEXT = 2
IDX_HEX = 3
IDX_FONT = 4
IDX_AUDIO = 5
IDX_VIDEO = 6
IDX_WEB = 7

_WEB_ENGINE_LOADED = False
_QWebEngineView = None
_QAudioOutput = None
_QMediaPlayer = None
_QVideoWidget = None


def _ensure_multimedia():
    global _QAudioOutput, _QMediaPlayer, _QVideoWidget
    if _QMediaPlayer is None:
        from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
        from PySide6.QtMultimediaWidgets import QVideoWidget
        _QMediaPlayer = QMediaPlayer
        _QAudioOutput = QAudioOutput
        _QVideoWidget = QVideoWidget


def _ensure_web_engine():
    global _WEB_ENGINE_LOADED, _QWebEngineView
    if not _WEB_ENGINE_LOADED:
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            _QWebEngineView = QWebEngineView
        except ImportError:
            _QWebEngineView = None
        _WEB_ENGINE_LOADED = True


class PreviewPane(QWidget):
    """Multi-format file preview widget with audio/video/HTML rendering."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_path = ""
        self._vgmstream_installing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._info_label = QLabel("Select a file to preview")
        self._info_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._info_label)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)

        # IDX_EMPTY = 0
        self._empty_widget = QWidget()
        empty_layout = QVBoxLayout(self._empty_widget)
        empty_layout.setAlignment(Qt.AlignCenter)
        self._empty_label = QLabel("No preview available")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet("font-size: 13px; padding: 16px;")
        empty_layout.addWidget(self._empty_label)
        self._stack.addWidget(self._empty_widget)

        # IDX_IMAGE = 1
        self._image_scroll = QScrollArea()
        self._image_scroll.setWidgetResizable(True)
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_scroll.setWidget(self._image_label)
        self._stack.addWidget(self._image_scroll)

        # IDX_TEXT = 2
        self._text_edit = QPlainTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setFont(QFont("Courier New", 10))
        self._text_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._stack.addWidget(self._text_edit)

        # IDX_HEX = 3
        self._hex_edit = QPlainTextEdit()
        self._hex_edit.setReadOnly(True)
        self._hex_edit.setFont(QFont("Courier New", 9))
        self._hex_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._stack.addWidget(self._hex_edit)

        # IDX_FONT = 4
        self._font_label = QLabel()
        self._font_label.setAlignment(Qt.AlignCenter)
        self._font_label.setWordWrap(True)
        self._stack.addWidget(self._font_label)

        # IDX_AUDIO = 5
        self._audio_container = QWidget()
        audio_layout = QVBoxLayout(self._audio_container)
        audio_layout.setContentsMargins(8, 8, 8, 8)
        self._audio_info = QLabel("")
        self._audio_info.setAlignment(Qt.AlignCenter)
        self._audio_info.setStyleSheet("font-size: 48px; padding: 20px;")
        self._audio_info.setText("Audio")
        audio_layout.addWidget(self._audio_info, 1)
        self._audio_player = AudioPlayerWidget(standalone=True)
        audio_layout.addWidget(self._audio_player)
        self._stack.addWidget(self._audio_container)

        # IDX_VIDEO = 6
        _ensure_multimedia()
        self._video_container = QWidget()
        video_layout = QVBoxLayout(self._video_container)
        video_layout.setContentsMargins(0, 0, 0, 0)
        self._video_widget = _QVideoWidget()
        video_layout.addWidget(self._video_widget, 1)
        self._video_player = _QMediaPlayer()
        self._video_audio = _QAudioOutput()
        self._video_player.setAudioOutput(self._video_audio)
        self._video_player.setVideoOutput(self._video_widget)
        # Video controls connected to video player
        self._video_controls = AudioPlayerWidget(standalone=False)
        self._video_controls.set_player(self._video_player, self._video_audio)
        video_layout.addWidget(self._video_controls)
        self._stack.addWidget(self._video_container)

        # IDX_WEB = 7
        self._web_view = None
        _ensure_web_engine()
        if _QWebEngineView is not None:
            self._web_view = _QWebEngineView()
            self._stack.addWidget(self._web_view)

        self._stack.setCurrentIndex(IDX_EMPTY)

    def preview_file(self, path: str) -> None:
        """Preview a file based on its detected type."""
        self._stop_media()

        if not os.path.isfile(path):
            self._show_empty("File not found")
            return

        self._current_path = path
        size = os.path.getsize(path)
        file_info = detect_file_type(path)
        self._info_label.setText(
            f"{os.path.basename(path)}  |  {file_info.description}  |  {format_file_size(size)}"
        )

        ext = file_info.extension.lower()

        if file_info.category == "image":
            self._show_image(path)
        elif file_info.category == "audio":
            self._show_audio(path)
        elif file_info.category == "video":
            self._show_video(path)
        elif file_info.category == "font":
            self._show_font(path)
        elif ext in (".html", ".thtml", ".css"):
            self._show_web(path, ext)
        elif file_info.category == "text" or file_info.can_edit:
            self._show_text(path)
        else:
            self._show_hex(path)

    def _stop_media(self) -> None:
        self._audio_player.cleanup()
        self._video_player.stop()
        self._video_player.setSource(QUrl())

    def _show_empty(self, message: str = "No preview available") -> None:
        self._empty_label.setText(message)
        self._stack.setCurrentIndex(IDX_EMPTY)

    def _show_image(self, path: str) -> None:
        ext = os.path.splitext(path)[1].lower()
        pixmap = QPixmap(path)

        if pixmap.isNull() and ext in (".dds", ".tga"):
            pixmap = self._convert_image_with_pillow(path)

        if pixmap is None or pixmap.isNull():
            self._show_empty(f"Cannot load image: {os.path.basename(path)}")
            return

        max_w = max(self._image_scroll.width() - 20, 200)
        max_h = max(self._image_scroll.height() - 20, 200)
        if pixmap.width() > max_w or pixmap.height() > max_h:
            pixmap = pixmap.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._image_label.setPixmap(pixmap)
        self._info_label.setText(
            self._info_label.text() + f"  |  {pixmap.width()}x{pixmap.height()}"
        )
        self._stack.setCurrentIndex(IDX_IMAGE)

    def _convert_image_with_pillow(self, path: str) -> QPixmap:
        """Convert DDS/TGA/other formats to QPixmap via Pillow."""
        try:
            from PIL import Image, ImageFile
            from PySide6.QtGui import QImage

            ImageFile.LOAD_TRUNCATED_IMAGES = True
            img = Image.open(path)
            img.load()
            img = img.convert("RGBA")
            data = img.tobytes("raw", "RGBA")
            qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format_RGBA8888)
            pixmap = QPixmap.fromImage(qimg.copy())
            ImageFile.LOAD_TRUNCATED_IMAGES = False
            return pixmap
        except Exception:
            return QPixmap()

    def _show_text(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(2 * 1024 * 1024)
            self._text_edit.setPlainText(content)
            self._stack.setCurrentIndex(IDX_TEXT)
        except Exception as e:
            self._show_empty(f"Cannot read file: {e}")

    def _show_hex(self, path: str) -> None:
        try:
            with open(path, "rb") as f:
                data = f.read(32768)
            lines = []
            for i in range(0, len(data), 16):
                chunk = data[i:i + 16]
                hex_part = " ".join(f"{b:02X}" for b in chunk)
                ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                lines.append(f"{i:08X}  {hex_part:<48s}  {ascii_part}")
            self._hex_edit.setPlainText("\n".join(lines))
            self._stack.setCurrentIndex(IDX_HEX)
        except Exception as e:
            self._show_empty(f"Cannot read file: {e}")

    def _show_font(self, path: str) -> None:
        try:
            from PySide6.QtGui import QFontDatabase
            font_id = QFontDatabase.addApplicationFont(path)
            if font_id >= 0:
                families = QFontDatabase.applicationFontFamilies(font_id)
                family = families[0] if families else "Unknown"
                preview_font = QFont(family, 24)
                sample = (
                    f"Font: {family}\n\n"
                    f"ABCDEFGHIJKLMNOPQRSTUVWXYZ\n"
                    f"abcdefghijklmnopqrstuvwxyz\n"
                    f"0123456789 !@#$%^&*()\n\n"
                    f"The quick brown fox jumps over the lazy dog."
                )
                self._font_label.setFont(preview_font)
                self._font_label.setText(sample)
            else:
                self._font_label.setText(f"Font file: {os.path.basename(path)}\n(Preview not available)")
            self._stack.setCurrentIndex(IDX_FONT)
        except Exception as e:
            self._show_empty(f"Cannot preview font: {e}")

    def _show_audio(self, path: str) -> None:
        ext = os.path.splitext(path)[1].lower()
        if ext in (".wem", ".bnk"):
            decoded = self._decode_wwise(path)
            if decoded:
                path = decoded
            else:
                # vgmstream not installed - auto-install silently
                self._silent_install_vgmstream(path)
                return

        ext_upper = os.path.splitext(path)[1].upper().lstrip(".")
        self._audio_info.setText(f"Audio\n{ext_upper}")
        self._audio_player.load_file(path)
        self._stack.setCurrentIndex(IDX_AUDIO)

    def _decode_wwise(self, path: str) -> str:
        """Decode a Wwise .wem/.bnk file to WAV using vgmstream-cli.

        Returns path to decoded WAV, or empty string on failure.
        """
        import subprocess
        import tempfile
        from utils.vgmstream_installer import get_vgmstream_path

        vgmstream = get_vgmstream_path()
        if not vgmstream:
            return ""

        basename = os.path.splitext(os.path.basename(path))[0]
        out_dir = tempfile.gettempdir()
        wav_path = os.path.join(out_dir, f"cf_decoded_{basename}.wav")

        if os.path.isfile(wav_path) and os.path.getsize(wav_path) > 0:
            return wav_path

        try:
            result = subprocess.run(
                [vgmstream, "-o", wav_path, path],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and os.path.isfile(wav_path):
                return wav_path
        except (subprocess.TimeoutExpired, OSError):
            pass
        return ""

    def _silent_install_vgmstream(self, pending_path: str) -> None:
        """Silently auto-install vgmstream, then play the file or ask to restart."""
        if self._vgmstream_installing:
            return

        self._vgmstream_installing = True
        self._show_empty("Installing audio decoder...\nPlease wait.")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

        from utils.vgmstream_installer import install_vgmstream

        def on_progress(msg):
            self._empty_label.setText(f"Installing audio decoder...\n{msg}")
            QApplication.processEvents()

        success, message = install_vgmstream(progress_callback=on_progress)
        self._vgmstream_installing = False

        if success:
            # Try to play immediately
            decoded = self._decode_wwise(pending_path)
            if decoded:
                ext_upper = os.path.splitext(pending_path)[1].upper().lstrip(".")
                self._audio_info.setText(f"Audio\n{ext_upper}")
                self._audio_player.load_file(decoded)
                self._stack.setCurrentIndex(IDX_AUDIO)
            else:
                # Installed but decode failed - ask to restart
                self._show_empty(
                    "Audio decoder installed successfully.\n\n"
                    "Please restart the app to play Wwise audio files."
                )
        else:
            # Install failed silently - just show can't play message
            self._show_empty(
                "Could not install audio decoder automatically.\n\n"
                "To play Wwise (.wem/.bnk) files, please restart the app\n"
                "or install vgmstream manually from vgmstream.org"
            )

    def _show_video(self, path: str) -> None:
        self._video_player.setSource(QUrl.fromLocalFile(path))
        self._video_controls._update_info(path)
        self._video_player.play()
        self._stack.setCurrentIndex(IDX_VIDEO)

    def _show_web(self, path: str, ext: str) -> None:
        """Show HTML/THTML/CSS as real rendered preview using QWebEngineView."""
        if self._web_view is None:
            self._show_text(path)
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(5 * 1024 * 1024)

            if ext == ".css":
                html = self._build_css_preview(content, path)
            else:
                html = content

            base_url = QUrl.fromLocalFile(os.path.dirname(path) + "/")
            self._web_view.setHtml(html, base_url)
            self._stack.setCurrentIndex(IDX_WEB)
        except Exception:
            self._show_text(path)

    def _build_css_preview(self, css_content: str, css_path: str) -> str:
        """Build an HTML page that renders actual CSS rules with real elements."""
        import re

        rules = re.findall(
            r'([^{]+)\{([^}]*)\}',
            css_content
        )

        html_parts = [
            "<!DOCTYPE html>\n<html><head>\n<meta charset='utf-8'>\n",
            f"<style>\n{css_content}\n</style>\n",
            "<style>\n",
            "body { background: #1e1e2e; margin: 0; padding: 12px; font-family: sans-serif; }\n",
            ".cf-rule { border: 1px solid #313244; border-radius: 6px; margin: 6px 0; padding: 10px; }\n",
            ".cf-sel { font-size: 11px; color: #6c7086; font-family: monospace; margin-bottom: 4px; }\n",
            "</style>\n</head><body>\n",
        ]

        for selector_raw, props in rules:
            selector = selector_raw.strip()
            if not selector or selector.startswith("@") or selector.startswith("/*"):
                continue

            parts = [s.strip() for s in selector.split(",")]
            for sel in parts:
                sel = sel.strip()
                if not sel:
                    continue

                tag = "div"
                classes = []
                sel_id = ""

                clean = re.split(r':{1,2}[\w-]+', sel)[0].strip()

                id_match = re.search(r'#([\w-]+)', clean)
                if id_match:
                    sel_id = id_match.group(1)
                    clean = clean[:id_match.start()] + clean[id_match.end():]

                class_matches = re.findall(r'\.([\w-]+)', clean)
                classes = class_matches

                tag_match = re.match(r'^([a-zA-Z][\w]*)', clean)
                if tag_match:
                    tag = tag_match.group(1)
                    if tag in ("html", "body", "head", "style", "script", "link", "meta"):
                        continue

                if tag in ("input", "textarea", "select", "button"):
                    element_tag = tag
                elif tag in ("img",):
                    element_tag = "div"
                else:
                    element_tag = tag

                cls_attr = f" class='{' '.join(classes)}'" if classes else ""
                id_attr = f" id='{sel_id}'" if sel_id else ""

                sample_text = sel
                if element_tag == "input":
                    inner = f"<input type='text' value='{sel}'{cls_attr}{id_attr} />"
                elif element_tag == "textarea":
                    inner = f"<textarea{cls_attr}{id_attr}>{sel}</textarea>"
                elif element_tag == "button":
                    inner = f"<button{cls_attr}{id_attr}>{sel}</button>"
                elif element_tag in ("br", "hr"):
                    inner = f"<{element_tag}{cls_attr}{id_attr} />"
                else:
                    inner = f"<{element_tag}{cls_attr}{id_attr}>{sample_text}</{element_tag}>"

                html_parts.append(
                    f"<div class='cf-rule'>"
                    f"<div class='cf-sel'>{_html_escape(selector)}</div>"
                    f"{inner}"
                    f"</div>\n"
                )

        html_parts.append("</body></html>")
        return "".join(html_parts)

    def clear(self) -> None:
        """Clear the preview pane and stop any media playback."""
        self._stop_media()
        self._info_label.setText("Select a file to preview")
        self._stack.setCurrentIndex(IDX_EMPTY)


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
