from domain.clinical_note import (
    ClinicalNoteAttachment,
    ClinicalNoteCode,
    ClinicalNoteData,
)


def test_clinical_note_defaults_are_builder_friendly():
    note = ClinicalNoteData()

    assert note.status == "current"
    assert note.doc_status == "final"
    assert note.language == "de-CH"
    assert note.attachments == []
    assert note.primary_attachment() is None
    assert note.has_identifier() is False
    assert note.has_narrative() is False
    assert note.has_attachments() is False


def test_clinical_note_helpers_cover_narrative_and_attachment_usage():
    attachment = ClinicalNoteAttachment(
        content_type="text/html",
        data="PGgxPk5vdGU8L2gxPg==",
        title="Clinical Note",
    )

    note = ClinicalNoteData(
        identifier_system="urn:oid:1.2.3",
        identifier_value="abc-123",
        title="Discharge Summary",
        subject_reference="Patient/pat-1",
        type_code=ClinicalNoteCode(
            system="http://loinc.org",
            code="18842-5",
            display="Discharge summary",
        ),
        narrative_text="Narrative content",
        attachments=[attachment],
    )

    assert note.has_identifier() is True
    assert note.has_narrative() is True
    assert note.has_attachments() is True
    assert note.primary_attachment() == attachment
    assert attachment.has_inline_data() is True
    assert attachment.has_reference() is False
