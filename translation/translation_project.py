"""Translation project manager - load, save, and manage translation projects.

A translation project is a JSON file that stores all translation entries,
their states, and metadata. Projects can be saved and reopened later.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from translation.translation_state import TranslationEntry, StringStatus
from utils.logger import get_logger

logger = get_logger("translation.project")


class TranslationProject:
    """Manages a translation project with persistent state."""

    def __init__(self):
        self._entries: list[TranslationEntry] = []
        self._index_map: dict[int, TranslationEntry] = {}
        self._source_lang: str = ""
        self._target_lang: str = ""
        self._source_file: str = ""
        self._project_file: str = ""
        self._modified: bool = False
        self._created_at: str = ""
        self._updated_at: str = ""

    def create_from_paloc(
        self,
        entries: list[tuple[str, str]],
        source_lang: str,
        target_lang: str,
        source_file: str,
    ) -> None:
        """Create a new project from paloc key-value pairs.

        Args:
            entries: List of (key, value) tuples from paloc parser.
            source_lang: Source language code.
            target_lang: Target language code.
            source_file: Path to the source paloc file.
        """
        self._entries = []
        for i, (key, value) in enumerate(entries):
            entry = TranslationEntry(
                index=i,
                key=key,
                original_text=value,
            )
            # Auto-lock untranslatable entries: empty text, developer
            # placeholders (PHM_, PHW_, PHF_, TODO, TBD).  These keep
            # their original value as the "translation" and are marked
            # APPROVED + locked so they cannot be edited or sent to AI.
            stripped = value.strip()
            if (not stripped
                    or stripped.startswith(("PHM_", "PHW_", "PHF_", "TODO", "TBD"))):
                entry.translated_text = value
                entry.status = StringStatus.APPROVED
                entry.locked = True
                entry.notes = "auto-locked: untranslatable"
            self._entries.append(entry)
        self._source_lang = source_lang
        self._target_lang = target_lang
        self._source_file = source_file
        self._created_at = datetime.now().isoformat()
        self._updated_at = self._created_at
        self._modified = True
        self._rebuild_index_map()
        logger.info("Created project: %d entries, %s -> %s", len(self._entries), source_lang, target_lang)

    def save(self, path: str = "") -> str:
        """Save the project to a JSON file.

        Args:
            path: File path to save to. Uses existing path if empty.

        Returns:
            Path the project was saved to.
        """
        if path:
            self._project_file = path
        if not self._project_file:
            raise ValueError(
                "No project file path specified. Use save(path) to set the save location."
            )

        self._updated_at = datetime.now().isoformat()

        data = {
            "version": "1.0.0",
            "source_lang": self._source_lang,
            "target_lang": self._target_lang,
            "source_file": self._source_file,
            "created_at": self._created_at,
            "updated_at": self._updated_at,
            "entry_count": len(self._entries),
            "stats": self._compute_stats(),
            "entries": [e.to_dict() for e in self._entries],
        }

        Path(self._project_file).parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._project_file + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self._project_file)

        self._modified = False
        logger.info("Project saved: %s", self._project_file)
        return self._project_file

    def load(self, path: str) -> None:
        """Load a project from a JSON file."""
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Project file not found: {path}. "
                f"Check that the file exists and has not been moved."
            )

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._source_lang = data["source_lang"]
        self._target_lang = data["target_lang"]
        self._source_file = data.get("source_file", "")
        self._created_at = data.get("created_at", "")
        self._updated_at = data.get("updated_at", "")
        self._project_file = path

        self._entries = []
        for entry_data in data.get("entries", []):
            self._entries.append(TranslationEntry.from_dict(entry_data))

        self._modified = False
        self._rebuild_index_map()
        logger.info("Project loaded: %s (%d entries)", path, len(self._entries))

    def _compute_stats(self) -> dict:
        stats = {s.value: 0 for s in StringStatus}
        for e in self._entries:
            stats[e.status.value] += 1
        stats["total"] = len(self._entries)
        return stats

    @property
    def entries(self) -> list[TranslationEntry]:
        return self._entries

    @property
    def source_lang(self) -> str:
        return self._source_lang

    @property
    def target_lang(self) -> str:
        return self._target_lang

    @target_lang.setter
    def target_lang(self, value: str):
        self._target_lang = value
        self._modified = True

    @property
    def source_file(self) -> str:
        return self._source_file

    @property
    def project_file(self) -> str:
        return self._project_file

    @property
    def modified(self) -> bool:
        return self._modified

    @modified.setter
    def modified(self, value: bool):
        self._modified = value

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def get_entry(self, index: int) -> Optional[TranslationEntry]:
        """Get entry by its .index property (NOT list position).
        Uses O(1) hash map lookup for 102K+ entries.
        """
        return self._index_map.get(index)

    def _rebuild_index_map(self):
        """Rebuild the index→entry hash map after entries change."""
        self._index_map = {e.index: e for e in self._entries}

    def get_pending_entries(self) -> list[TranslationEntry]:
        return [e for e in self._entries if e.status == StringStatus.PENDING]

    def get_entries_by_status(self, status: StringStatus) -> list[TranslationEntry]:
        return [e for e in self._entries if e.status == status]

    def get_stats(self) -> dict:
        return self._compute_stats()

    def mark_modified(self):
        self._modified = True
