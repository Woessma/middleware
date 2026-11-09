import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from builders.ch_core_composition_builder import build_ch_core_composition
from mappers.author_helpers import add_author_display
from services import cda_bundle_service
from utils.fhir_utils import fhir_decimal


class CdaR4StructureTests(unittest.TestCase):
    def test_numeric_values_are_finite_json_numbers(self):
        self.assertEqual(fhir_decimal("1.25"), 1.25)
        self.assertEqual(fhir_decimal("-2"), -2)
        for value in ("NaN", "Infinity", "not a number"):
            with self.assertRaises(ValueError):
                fhir_decimal(value)

    def test_authorship_uses_supported_fields_without_inventing_careteam_members(self):
        goal = add_author_display({"resourceType": "Goal"}, {"authorDisplay": "Synthetic"})
        team = add_author_display({"resourceType": "CareTeam"}, {"authorDisplay": "Synthetic"})
        self.assertNotIn("author", goal)
        self.assertEqual(goal["expressedBy"], {"display": "Synthetic"})
        self.assertNotIn("author", team)
        self.assertNotIn("participant", team)
        self.assertEqual(team["note"], [{"text": "CDA author: Synthetic"}])

    def test_empty_section_preserves_escaped_source_narrative(self):
        composition = build_ch_core_composition(
            patient_reference="Patient/synthetic",
            document_type_code={"code": "synthetic"},
            title="Synthetic", date="2026-01-01",
            section_summaries=[{
                "title": "Synthetic", "narrativeText": "A < B & C",
            }],
            clinical_note_references=[],
        )
        self.assertIn("A &lt; B &amp; C", composition["section"][0]["text"]["div"])

    def test_section_preserves_narrative_alongside_resource_references(self):
        composition = build_ch_core_composition(
            patient_reference="Patient/synthetic",
            document_type_code={"code": "synthetic"},
            title="Synthetic", date="2026-01-01",
            section_summaries=[{
                "title": "Resultate",
                "code": {"code": "30954-2"},
                "narrativeText": "Glucose < 6 mmol/L",
            }],
            clinical_note_references=[],
            section_resource_references=[{
                "reference": "DiagnosticReport/report-1",
                "sectionCode": "30954-2",
                "sectionTitle": "Resultate",
            }],
        )

        section = composition["section"][0]
        self.assertEqual(
            section["entry"],
            [{"reference": "DiagnosticReport/report-1"}],
        )
        self.assertIn("Glucose &lt; 6 mmol/L", section["text"]["div"])

    def test_document_references_resolve_and_entries_have_no_transaction_fields(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"entry": []}
        with (
            patch("fhir.bundle.requests.get", return_value=response),
            patch.object(cda_bundle_service, "resolve_patient_id", return_value="synthetic-patient"),
            patch.object(cda_bundle_service, "resolve_practitioner_id", return_value="synthetic-practitioner"),
            patch.object(cda_bundle_service, "resolve_organization_id", return_value="synthetic-organization"),
        ):
            bundle = cda_bundle_service.cda_to_fhir_bundle(
                (Path(__file__).parent / "data" / "CDA-EPIC.xml").read_bytes(),
                bundle_type="document",
            )
        self.assertEqual(bundle["entry"][0]["resource"]["resourceType"], "Composition")
        urls = {entry["fullUrl"] for entry in bundle["entry"]}
        references = []

        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "reference":
                        references.append(item)
                    else:
                        walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(bundle)
        self.assertTrue(references)
        self.assertTrue(all(reference in urls for reference in references))
        for entry in bundle["entry"]:
            self.assertNotIn("request", entry)
            self.assertNotIn("response", entry)
        self.assertNotIn(
            "http://fhir.ch/ig/ch-ips/StructureDefinition/ch-ips-composition",
            bundle["entry"][0]["resource"]["meta"]["profile"],
        )
