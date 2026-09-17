import base64
import hashlib
import uuid

from domain.clinical_note import (
    ClinicalNoteAttachment,
    ClinicalNoteData,
)


def _build_binary_id(
    note: ClinicalNoteData,
    attachment_index: int,
) -> str:
    identifier_value = note.identifier_value or note.title or "clinical-note"

    stable_uuid = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"binary|{identifier_value}|{attachment_index}",
    )

    return f"binary-{stable_uuid}"


def _attachment_bytes(
    attachment: ClinicalNoteAttachment,
) -> bytes:
    if not attachment.data:
        return b""

    return base64.b64decode(attachment.data)


def build_binary_resource(
    note: ClinicalNoteData,
    attachment: ClinicalNoteAttachment,
    attachment_index: int = 0,
) -> dict:
    resource = {
        "resourceType": "Binary",
        "id": _build_binary_id(note, attachment_index),
        "contentType": attachment.content_type,
    }

    if attachment.data:
        resource["data"] = attachment.data

    if note.subject_reference:
        resource["securityContext"] = {
            "reference": note.subject_reference,
        }

    return resource


def build_binary_attachment_reference(
    note: ClinicalNoteData,
    attachment: ClinicalNoteAttachment,
    attachment_index: int = 0,
) -> ClinicalNoteAttachment:
    payload = _attachment_bytes(attachment)

    # For inline payloads, derive hash/size from bytes to avoid stale metadata.
    hash_value = attachment.hash_value
    size = attachment.size

    if payload:
        hash_value = base64.b64encode(
            hashlib.sha1(payload).digest()
        ).decode("ascii")
        size = len(payload)

    return ClinicalNoteAttachment(
        content_type=attachment.content_type,
        language=attachment.language,
        title=attachment.title,
        creation=attachment.creation,
        url=f"Binary/{_build_binary_id(note, attachment_index)}",
        size=size,
        hash_value=hash_value,
    )
