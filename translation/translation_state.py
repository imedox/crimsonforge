"""Per-string translation state machine.

Each localization string goes through states:
  Pending -> Translated -> Reviewed -> Approved
  (can revert at any time)
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class StringStatus(Enum):
    PENDING = "pending"
    TRANSLATED = "translated"
    REVIEWED = "reviewed"
    APPROVED = "approved"


@dataclass
class TranslationEntry:
    """State of a single translation string."""
    index: int
    key: str
    original_text: str
    translated_text: str = ""
    status: StringStatus = StringStatus.PENDING
    usage_tags: list[str] = field(default_factory=list)
    ai_provider: str = ""
    ai_model: str = ""
    ai_tokens: int = 0
    ai_cost: float = 0.0
    manually_edited: bool = False
    locked: bool = False
    notes: str = ""

    def set_translated(self, text: str, provider: str = "", model: str = "",
                       tokens: int = 0, cost: float = 0.0) -> None:
        """Set translation from AI or manual input."""
        self.translated_text = text
        self.status = StringStatus.TRANSLATED
        if provider:
            self.ai_provider = provider
            self.ai_model = model
            self.ai_tokens = tokens
            self.ai_cost = cost
            self.manually_edited = False
        else:
            self.manually_edited = True

    def set_reviewed(self) -> None:
        if self.status in (StringStatus.TRANSLATED, StringStatus.APPROVED):
            self.status = StringStatus.REVIEWED

    def set_approved(self) -> None:
        if self.status in (StringStatus.TRANSLATED, StringStatus.REVIEWED):
            self.status = StringStatus.APPROVED

    def revert_to_pending(self) -> None:
        if self.locked:
            return
        self.status = StringStatus.PENDING
        self.translated_text = ""
        self.ai_provider = ""
        self.ai_model = ""
        self.ai_tokens = 0
        self.ai_cost = 0.0
        self.manually_edited = False

    def edit_translation(self, new_text: str) -> None:
        """Manually edit an existing translation."""
        if self.locked:
            return
        self.translated_text = new_text
        self.manually_edited = True
        if self.status == StringStatus.APPROVED:
            self.status = StringStatus.REVIEWED

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "key": self.key,
            "original_text": self.original_text,
            "translated_text": self.translated_text,
            "status": self.status.value,
            "usage_tags": list(self.usage_tags),
            "ai_provider": self.ai_provider,
            "ai_model": self.ai_model,
            "ai_tokens": self.ai_tokens,
            "ai_cost": self.ai_cost,
            "manually_edited": self.manually_edited,
            "locked": self.locked,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TranslationEntry":
        entry = cls(
            index=data["index"],
            key=data["key"],
            original_text=data["original_text"],
            translated_text=data.get("translated_text", ""),
            usage_tags=list(data.get("usage_tags", [])),
            ai_provider=data.get("ai_provider", ""),
            ai_model=data.get("ai_model", ""),
            ai_tokens=data.get("ai_tokens", 0),
            ai_cost=data.get("ai_cost", 0.0),
            manually_edited=data.get("manually_edited", False),
            locked=data.get("locked", False),
            notes=data.get("notes", ""),
        )
        status_str = data.get("status", "pending")
        entry.status = StringStatus(status_str)
        return entry
