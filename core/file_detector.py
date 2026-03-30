"""File type detection from content and extensions.

Detects file types using magic bytes and file extensions to determine
the appropriate viewer/editor in the Browse and Edit tabs.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class FileTypeInfo:
    """Detected file type information."""
    category: str       # 'image', 'audio', 'video', 'text', 'font', 'binary', 'archive'
    mime_type: str       # MIME type string
    description: str     # Human-readable description
    extension: str       # Normalized extension (lowercase, with dot)
    can_preview: bool    # Whether the file can be previewed in Browse tab
    can_edit: bool       # Whether the file can be edited in Edit tab


EXTENSION_MAP = {
    ".png":   FileTypeInfo("image", "image/png", "PNG Image", ".png", True, False),
    ".jpg":   FileTypeInfo("image", "image/jpeg", "JPEG Image", ".jpg", True, False),
    ".jpeg":  FileTypeInfo("image", "image/jpeg", "JPEG Image", ".jpeg", True, False),
    ".bmp":   FileTypeInfo("image", "image/bmp", "BMP Image", ".bmp", True, False),
    ".tga":   FileTypeInfo("image", "image/x-tga", "TGA Image", ".tga", True, False),
    ".dds":   FileTypeInfo("image", "image/vnd-ms.dds", "DDS Texture", ".dds", True, False),
    ".webp":  FileTypeInfo("image", "image/webp", "WebP Image", ".webp", True, False),
    ".gif":   FileTypeInfo("image", "image/gif", "GIF Image", ".gif", True, False),
    ".wav":   FileTypeInfo("audio", "audio/wav", "WAV Audio", ".wav", True, False),
    ".ogg":   FileTypeInfo("audio", "audio/ogg", "OGG Audio", ".ogg", True, False),
    ".mp3":   FileTypeInfo("audio", "audio/mpeg", "MP3 Audio", ".mp3", True, False),
    ".wem":   FileTypeInfo("audio", "audio/x-wem", "Wwise Audio (WEM)", ".wem", True, False),
    ".bnk":   FileTypeInfo("audio", "audio/x-bnk", "Wwise SoundBank (BNK)", ".bnk", True, False),
    ".pasound": FileTypeInfo("audio", "audio/x-pasound", "PA Sound Config", ".pasound", True, False),
    ".flac":  FileTypeInfo("audio", "audio/flac", "FLAC Audio", ".flac", True, False),
    ".aac":   FileTypeInfo("audio", "audio/aac", "AAC Audio", ".aac", True, False),
    ".mp4":   FileTypeInfo("video", "video/mp4", "MP4 Video", ".mp4", True, False),
    ".webm":  FileTypeInfo("video", "video/webm", "WebM Video", ".webm", True, False),
    ".avi":   FileTypeInfo("video", "video/x-msvideo", "AVI Video", ".avi", True, False),
    ".mkv":   FileTypeInfo("video", "video/x-matroska", "MKV Video", ".mkv", True, False),
    ".bk2":   FileTypeInfo("video", "video/x-bink2", "Bink2 Video", ".bk2", True, False),
    ".bik":   FileTypeInfo("video", "video/x-bink", "Bink Video", ".bik", True, False),
    ".usm":   FileTypeInfo("video", "video/x-usm", "CriWare USM Video", ".usm", True, False),
    ".css":   FileTypeInfo("text", "text/css", "CSS Stylesheet", ".css", True, True),
    ".html":  FileTypeInfo("text", "text/html", "HTML Document", ".html", True, True),
    ".thtml": FileTypeInfo("text", "text/html", "Template HTML", ".thtml", True, True),
    ".xml":   FileTypeInfo("text", "application/xml", "XML Document", ".xml", True, True),
    ".json":  FileTypeInfo("text", "application/json", "JSON Data", ".json", True, True),
    ".txt":   FileTypeInfo("text", "text/plain", "Text File", ".txt", True, True),
    ".csv":   FileTypeInfo("text", "text/csv", "CSV Data", ".csv", True, True),
    ".paloc": FileTypeInfo("text", "application/x-paloc", "Localization File", ".paloc", True, True),
    ".ttf":   FileTypeInfo("font", "font/ttf", "TrueType Font", ".ttf", True, False),
    ".otf":   FileTypeInfo("font", "font/otf", "OpenType Font", ".otf", True, False),
    ".woff":  FileTypeInfo("font", "font/woff", "WOFF Font", ".woff", True, False),
    ".woff2": FileTypeInfo("font", "font/woff2", "WOFF2 Font", ".woff2", True, False),
    ".paz":   FileTypeInfo("archive", "application/x-paz", "PAZ Archive", ".paz", False, False),
    ".pamt":  FileTypeInfo("archive", "application/x-pamt", "PAMT Index", ".pamt", False, False),
    ".papgt": FileTypeInfo("archive", "application/x-papgt", "PAPGT Root Index", ".papgt", False, False),
}

MAGIC_BYTES = {
    b"\x89PNG\r\n\x1a\n": ".png",
    b"\xff\xd8\xff": ".jpg",
    b"BM": ".bmp",
    b"GIF87a": ".gif",
    b"GIF89a": ".gif",
    b"RIFF": ".wav",
    b"OggS": ".ogg",
    b"\xff\xfb": ".mp3",
    b"\xff\xf3": ".mp3",
    b"\xff\xf2": ".mp3",
    b"ID3": ".mp3",
    b"DDS ": ".dds",
    b"fLaC": ".flac",
    b"BIKi": ".bk2",
    b"BIKh": ".bk2",
    b"CRID": ".usm",
    b"\x00\x00\x01\x00": ".ttf",
    b"\x00\x01\x00\x00": ".ttf",
    b"OTTO": ".otf",
    b"wOFF": ".woff",
    b"wOF2": ".woff2",
    b"<?xml": ".xml",
    b"<html": ".html",
    b"<!DOCTYPE": ".html",
}


def detect_file_type(path: str, data: Optional[bytes] = None) -> FileTypeInfo:
    """Detect file type from extension and optionally magic bytes.

    Args:
        path: File path (used for extension matching).
        data: Optional file content for magic byte detection.

    Returns:
        FileTypeInfo describing the detected file type.
    """
    ext = os.path.splitext(path)[1].lower()

    if ext in EXTENSION_MAP:
        return EXTENSION_MAP[ext]

    if data and len(data) >= 8:
        for magic, magic_ext in MAGIC_BYTES.items():
            if data[:len(magic)] == magic:
                if magic_ext in EXTENSION_MAP:
                    return EXTENSION_MAP[magic_ext]

    return FileTypeInfo(
        category="binary",
        mime_type="application/octet-stream",
        description="Binary File",
        extension=ext or ".bin",
        can_preview=True,
        can_edit=False,
    )


def get_syntax_type(path: str) -> str:
    """Get the syntax highlighting type for a text file.

    Returns a string suitable for syntax highlighter selection:
    'css', 'html', 'xml', 'json', 'paloc', 'plain'.
    """
    ext = os.path.splitext(path)[1].lower()
    syntax_map = {
        ".css": "css",
        ".html": "html",
        ".thtml": "html",
        ".xml": "xml",
        ".json": "json",
        ".paloc": "paloc",
        ".txt": "plain",
        ".csv": "plain",
    }
    return syntax_map.get(ext, "plain")


def is_text_file(path: str) -> bool:
    """Check if a file is a text file that can be opened in the editor."""
    info = detect_file_type(path)
    return info.can_edit


def is_previewable(path: str) -> bool:
    """Check if a file can be previewed in the Browse tab."""
    info = detect_file_type(path)
    return info.can_preview
