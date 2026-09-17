from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ClinicalNoteCode:

    system: Optional[str] = None
    code: Optional[str] = None
    display: Optional[str] = None
    text: Optional[str] = None


@dataclass
class ClinicalNoteAttachment:

    content_type: str

    language: Optional[str] = None
    title: Optional[str] = None
    creation: Optional[str] = None

    data: Optional[str] = None
    url: Optional[str] = None

    size: Optional[int] = None
    hash_value: Optional[str] = None

    def has_inline_data(self) -> bool:
        return bool(self.data)

    def has_reference(self) -> bool:
        return bool(self.url)


@dataclass
class ClinicalNoteData:

    identifier_system: Optional[str] = None
    identifier_value: Optional[str] = None

    status: str = "current"
    doc_status: str = "final"
    language: str = "de-CH"

    title: Optional[str] = None
    description: Optional[str] = None

    subject_reference: Optional[str] = None
    encounter_reference: Optional[str] = None

    author_reference: Optional[str] = None
    author_display: Optional[str] = None

    custodian_reference: Optional[str] = None
    custodian_display: Optional[str] = None

    type_code: Optional[ClinicalNoteCode] = None
    category_code: Optional[ClinicalNoteCode] = None
    practice_setting_code: Optional[ClinicalNoteCode] = None

    created_at: Optional[str] = None
    effective_at: Optional[str] = None

    source_section_code: Optional[str] = None
    source_section_title: Optional[str] = None

    narrative_html: Optional[str] = None
    narrative_text: Optional[str] = None

    attachments: list[ClinicalNoteAttachment] = field(default_factory=list)

    def has_identifier(self) -> bool:
        return bool(
            self.identifier_system and
            self.identifier_value
        )

    def has_narrative(self) -> bool:
        return bool(
            self.narrative_html or
            self.narrative_text
        )

    def has_attachments(self) -> bool:
        return bool(self.attachments)

    def primary_attachment(self) -> Optional[ClinicalNoteAttachment]:
        if not self.attachments:
            return None

        return self.attachments[0]
