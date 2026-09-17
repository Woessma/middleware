import base64
import hashlib

from domain.clinical_note import (
    ClinicalNoteAttachment,
    ClinicalNoteCode,
    ClinicalNoteData,
)
from fhir.fhir_helpers import oid_to_fhir_system


CLINICAL_NOTE_IDENTIFIER_SYSTEM = (
    "https://woess.ch/fhir/NamingSystem/cda-import-clinical-note"
)

CLINICAL_NOTE_SECTION_CODES = {
    "BRIEFT",
    "42348-3",
    "56825-3",
    "55752-0",
    "ABBEM",
    "BEIL",
}


def _section_title(section: dict) -> str:
    code = section.get("code") or {}

    return (
        section.get("title")
        or code.get("displayName")
        or "Clinical Note"
    )


def is_clinical_note_section(section: dict) -> bool:
    narrative_text = (section.get("narrativeText") or "").strip()
    attachments = section.get("attachments") or []

    has_content = bool(narrative_text or attachments)

    if not has_content:
        return False

    code = (section.get("code") or {}).get("code")

    if code in CLINICAL_NOTE_SECTION_CODES:
        return True

    title = _section_title(section).lower()

    return any(
        marker in title
        for marker in (
            "brief",
            "verlauf",
            "dekurs",
            "information",
            "bemerk",
            "willenserklärung",
            "jurid",
            "beilage",
        )
    )


def _build_note_identifier(section: dict) -> str:
    code = section.get("code") or {}
    narrative_text = section.get("narrativeText") or ""
    title = _section_title(section)
    attachments = section.get("attachments") or []
    attachment_identity = "|".join(
        f"{item.get('contentType')}:{item.get('id')}:{len(item.get('data') or '')}"
        for item in attachments
    )

    raw_value = "|".join(
        [
            code.get("code") or "",
            title,
            narrative_text,
            attachment_identity,
        ]
    )

    return hashlib.sha256(
        raw_value.encode("utf-8")
    ).hexdigest()


def build_clinical_note_from_section(
    section: dict,
    patient_reference: str,
    document_datetime: str | None = None,
    encounter_reference: str | None = None,
) -> ClinicalNoteData | None:
    if not is_clinical_note_section(section):
        return None

    code = section.get("code") or {}
    title = _section_title(section)
    narrative_text = (section.get("narrativeText") or "").strip()
    identifier_value = _build_note_identifier(section)

    type_code = ClinicalNoteCode(
        system=oid_to_fhir_system(code.get("codeSystem")),
        code=code.get("code"),
        display=code.get("displayName"),
        text=title,
    )

    attachments = []

    if narrative_text:
        attachments.append(
            ClinicalNoteAttachment(
                content_type="text/plain",
                language="de-CH",
                title=title,
                creation=document_datetime,
                data=base64.b64encode(
                    narrative_text.encode("utf-8")
                ).decode("ascii"),
                size=len(narrative_text.encode("utf-8")),
            )
        )

    if code.get("code") == "BEIL":
        for item in section.get("attachments") or []:
            attachments.append(
                ClinicalNoteAttachment(
                    content_type=item.get("contentType") or "application/octet-stream",
                    title=item.get("title") or title,
                    creation=document_datetime,
                    data=item.get("data"),
                )
            )

    return ClinicalNoteData(
        identifier_system=CLINICAL_NOTE_IDENTIFIER_SYSTEM,
        identifier_value=identifier_value,
        title=title,
        description=code.get("displayName") or title,
        subject_reference=patient_reference,
        encounter_reference=encounter_reference,
        type_code=type_code,
        created_at=document_datetime,
        effective_at=document_datetime,
        source_section_code=code.get("code"),
        source_section_title=title,
        narrative_text=narrative_text,
        attachments=attachments,
    )


def extract_clinical_notes(
    sections: list[dict],
    patient_reference: str,
    document_datetime: str | None = None,
    encounter_reference: str | None = None,
) -> list[ClinicalNoteData]:
    notes = []

    for section in sections:
        note = build_clinical_note_from_section(
            section,
            patient_reference,
            document_datetime=document_datetime,
            encounter_reference=encounter_reference,
        )

        if note:
            notes.append(note)

    return notes
