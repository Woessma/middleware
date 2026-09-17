import base64

from domain.clinical_note import (
    ClinicalNoteAttachment,
    ClinicalNoteCode,
    ClinicalNoteData,
)
from builders.binary_builder import (
    build_binary_attachment_reference,
    build_binary_resource,
)


CH_CORE_DOCUMENT_REFERENCE_PROFILE = (
    "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-documentreference"
)


def _build_codeable_concept(note_code: ClinicalNoteCode | None) -> dict | None:
    if note_code is None:
        return None

    result = {}

    if note_code.code:
        coding = {
            "code": note_code.code,
        }

        if note_code.system:
            coding["system"] = note_code.system

        if note_code.display:
            coding["display"] = note_code.display

        result["coding"] = [coding]

    if note_code.text:
        result["text"] = note_code.text

    return result or None


def _build_attachment(attachment: ClinicalNoteAttachment) -> dict:
    result = {
        "contentType": attachment.content_type,
    }

    if attachment.language:
        result["language"] = attachment.language

    if attachment.title:
        result["title"] = attachment.title

    if attachment.creation:
        result["creation"] = attachment.creation

    if attachment.data:
        result["data"] = attachment.data

    if attachment.url:
        result["url"] = attachment.url

    if attachment.size is not None:
        result["size"] = attachment.size

    if attachment.hash_value:
        result["hash"] = attachment.hash_value

    return result


def _build_default_attachment(note: ClinicalNoteData) -> ClinicalNoteAttachment | None:
    if note.narrative_html:
        payload = note.narrative_html.encode("utf-8")
        return ClinicalNoteAttachment(
            content_type="text/html",
            language=note.language,
            title=note.title,
            creation=note.created_at,
            data=base64.b64encode(payload).decode("ascii"),
            size=len(payload),
        )

    if note.narrative_text:
        payload = note.narrative_text.encode("utf-8")
        return ClinicalNoteAttachment(
            content_type="text/plain",
            language=note.language,
            title=note.title,
            creation=note.created_at,
            data=base64.b64encode(payload).decode("ascii"),
            size=len(payload),
        )

    return None


def _resolve_attachments(note: ClinicalNoteData) -> list[ClinicalNoteAttachment]:
    if note.attachments:
        return note.attachments

    default_attachment = _build_default_attachment(note)

    if default_attachment is None:
        return []

    return [default_attachment]


def build_document_reference(
    note: ClinicalNoteData,
    attachments: list[ClinicalNoteAttachment] | None = None,
) -> dict:
    resource = {
        "resourceType": "DocumentReference",
        "meta": {
            "profile": [
                CH_CORE_DOCUMENT_REFERENCE_PROFILE,
            ]
        },
        "status": note.status,
        "docStatus": note.doc_status,
        "content": [],
    }

    if note.has_identifier():
        resource["identifier"] = [
            {
                "system": note.identifier_system,
                "value": note.identifier_value,
            }
        ]

    if note.subject_reference:
        resource["subject"] = {
            "reference": note.subject_reference,
        }

    if note.type_code:
        type_code = _build_codeable_concept(note.type_code)
        if type_code:
            resource["type"] = type_code

    if note.category_code:
        category_code = _build_codeable_concept(note.category_code)
        if category_code:
            resource["category"] = [category_code]

    if note.practice_setting_code:
        practice_setting = _build_codeable_concept(note.practice_setting_code)
        if practice_setting:
            resource["context"] = resource.get("context", {})
            resource["context"]["practiceSetting"] = practice_setting

    if note.title:
        resource["description"] = note.title

    if note.created_at:
        resource["date"] = note.created_at

    if note.author_reference or note.author_display:
        author = {}
        if note.author_reference:
            author["reference"] = note.author_reference
        if note.author_display:
            author["display"] = note.author_display
        resource["author"] = [author]

    if note.custodian_reference or note.custodian_display:
        custodian = {}
        if note.custodian_reference:
            custodian["reference"] = note.custodian_reference
        if note.custodian_display:
            custodian["display"] = note.custodian_display
        resource["custodian"] = custodian

    if note.encounter_reference:
        resource["context"] = resource.get("context", {})
        resource["context"]["encounter"] = [
            {
                "reference": note.encounter_reference,
            }
        ]

    attachments = attachments or _resolve_attachments(note)

    resource["content"] = [
        {
            "attachment": _build_attachment(attachment)
        }
        for attachment in attachments
    ]

    return resource


def build_document_reference_with_binaries(
    note: ClinicalNoteData,
) -> tuple[dict, list[dict]]:
    attachments = _resolve_attachments(note)
    binary_resources = []
    referenced_attachments = []

    for index, attachment in enumerate(attachments):
        if attachment.has_inline_data():
            binary_resources.append(
                build_binary_resource(
                    note,
                    attachment,
                    attachment_index=index,
                )
            )
            referenced_attachments.append(
                build_binary_attachment_reference(
                    note,
                    attachment,
                    attachment_index=index,
                )
            )
            continue

        referenced_attachments.append(attachment)

    document_reference = build_document_reference(
        note,
        attachments=referenced_attachments,
    )

    return document_reference, binary_resources
