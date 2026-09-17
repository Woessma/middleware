import base64
import hashlib
import unittest
from xml.etree import ElementTree as ET

from builders.document_reference_builder import (
    build_document_reference,
    build_document_reference_with_binaries,
)
from converter.clinical_note_extractor import extract_clinical_notes
from parser.cda.section_parser import extract_sections


class ClinicalNoteBuilderTests(unittest.TestCase):
    def test_cda_at_narrative_sections_become_clinical_notes(self):
        root = ET.parse(
            "app/tests/data/CDA-AT.xml"
        ).getroot()

        sections = extract_sections(root)

        notes = extract_clinical_notes(
            sections,
            patient_reference="Patient/123",
        )

        titles = {note.title for note in notes}

        self.assertGreaterEqual(len(notes), 8)
        self.assertIn("Brieftext", titles)
        self.assertIn("Verlauf", titles)
        self.assertIn("Dekurs vom 10.08.2019", titles)
        self.assertIn("Weitere Informationen", titles)
        self.assertIn("Abschließende Bemerkungen", titles)
        self.assertIn("Willenserklärungen und andere juridische Dokumente", titles)
        self.assertIn("Beilagen", titles)

    def test_document_reference_builder_uses_narrative_attachment(self):
        root = ET.parse(
            "app/tests/data/CDA-AT.xml"
        ).getroot()

        sections = extract_sections(root)
        notes = extract_clinical_notes(
            sections,
            patient_reference="Patient/123",
        )

        document_reference = build_document_reference(notes[0])
        attachment = document_reference["content"][0]["attachment"]

        self.assertEqual(
            document_reference["resourceType"],
            "DocumentReference",
        )
        self.assertEqual(
            document_reference["meta"]["profile"][0],
            "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-documentreference",
        )
        self.assertEqual(document_reference["status"], "current")
        self.assertEqual(document_reference["docStatus"], "final")
        self.assertEqual(
            document_reference["subject"]["reference"],
            "Patient/123",
        )
        self.assertEqual(
            attachment["contentType"],
            "text/plain",
        )
        self.assertTrue(attachment["data"])

        decoded = base64.b64decode(
            attachment["data"]
        ).decode("utf-8")

        self.assertEqual(decoded, notes[0].narrative_text)

    def test_document_reference_builder_can_externalize_attachment_as_binary(self):
        root = ET.parse(
            "app/tests/data/CDA-AT.xml"
        ).getroot()

        sections = extract_sections(root)
        notes = extract_clinical_notes(
            sections,
            patient_reference="Patient/123",
        )

        document_reference, binary_resources = (
            build_document_reference_with_binaries(notes[0])
        )

        self.assertEqual(len(binary_resources), 1)
        self.assertEqual(binary_resources[0]["resourceType"], "Binary")
        self.assertEqual(
            binary_resources[0]["securityContext"]["reference"],
            "Patient/123",
        )

        attachment = document_reference["content"][0]["attachment"]

        self.assertNotIn("data", attachment)
        self.assertTrue(attachment["url"].startswith("Binary/"))
        self.assertEqual(
            attachment["url"],
            f"Binary/{binary_resources[0]['id']}",
        )
        self.assertTrue(attachment["hash"])
        self.assertGreater(attachment["size"], 0)

    def test_cda_at_attachment_section_becomes_pdf_clinical_note(self):
        root = ET.parse(
            "app/tests/data/CDA-AT.xml"
        ).getroot()

        sections = extract_sections(root)
        notes = extract_clinical_notes(
            sections,
            patient_reference="Patient/123",
        )

        attachment_note = next(
            note for note in notes
            if note.title == "Beilagen"
        )

        self.assertEqual(
            attachment_note.source_section_code,
            "BEIL",
        )
        self.assertEqual(len(attachment_note.attachments), 1)
        self.assertEqual(
            attachment_note.attachments[0].content_type,
            "application/pdf",
        )
        self.assertTrue(
            attachment_note.attachments[0].has_inline_data()
        )

    def test_externalized_binary_attachment_recomputes_hash_and_size_from_payload(self):
        root = ET.parse(
            "app/tests/data/CDA-AT.xml"
        ).getroot()

        sections = extract_sections(root)
        notes = extract_clinical_notes(
            sections,
            patient_reference="Patient/123",
        )

        attachment_note = next(
            note for note in notes
            if note.title == "Beilagen"
        )

        # Simulate stale metadata from a previous version/update path.
        attachment_note.attachments[0].hash_value = "stale-hash"
        attachment_note.attachments[0].size = 1

        document_reference, _binary_resources = (
            build_document_reference_with_binaries(attachment_note)
        )

        attachment = document_reference["content"][0]["attachment"]
        payload = base64.b64decode(
            attachment_note.attachments[0].data
        )
        expected_hash = base64.b64encode(
            hashlib.sha1(payload).digest()
        ).decode("ascii")

        self.assertEqual(attachment["hash"], expected_hash)
        self.assertEqual(attachment["size"], len(payload))


if __name__ == "__main__":
    unittest.main()
