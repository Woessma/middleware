import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

from converter.section_dispatcher import get_section_mapper
from mappers.condition_mapper import map_condition_section
from mappers.encounter_mapper import map_encounter_section
from mappers.lab_mapper import map_lab_section
from mappers.medication_mapper import map_medication_section
from mappers.procedure_mapper import map_procedure_section
from parser.cda.section_parser import extract_sections


class EpicSectionMapperTests(unittest.TestCase):
    @patch("mappers.medication_mapper.resolve_medication_identity")
    def test_cda_medication_adds_canonical_gtin_for_pharmacode(self, mock_resolve):
        mock_resolve.return_value = {
            "gtin": "7680485780715",
            "product_number": "48578071",
            "display": "Torem 10, Tabletten",
            "dispensing_category": "B",
        }

        resources = map_medication_section(
            {
                "entries": [
                    {
                        "consumable": {
                            "code": {
                                "code": "1551274",
                                "codeSystem": "https://emediplan.ch/fhir/NamingSystem/pharmacode",
                            }
                        }
                    }
                ]
            },
            "Patient/p1",
            {},
        )

        codings = resources[0]["medicationCodeableConcept"]["coding"]
        self.assertIn(
            {"system": "urn:epc:id:sgtin", "code": "7680485780715", "display": "Torem 10, Tabletten"},
            codings,
        )
        self.assertIn(
            {"system": "https://emediplan.ch/fhir/NamingSystem/pharmacode", "code": "1551274"},
            [{"system": item.get("system"), "code": item.get("code")} for item in codings],
        )
        self.assertEqual(
            resources[0]["extension"][0]["valueCode"],
            "B",
        )

    def test_resolved_problems_are_mapped_to_condition_with_resolved_status(self):
        section = {
            "entries": [
                {
                    "code": {"code": "64572001"},
                    "value": {"code": "54888009", "displayName": "Kniedistorsion"},
                    "allergyStatus": {"displayName": "Resolved"},
                    "effectiveDateTime": "2024-02-08"
                }
            ]
        }

        resources = map_condition_section(section, "Patient/123", {})

        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["resourceType"], "Condition")
        self.assertEqual(resources[0]["clinicalStatus"]["coding"][0]["code"], "resolved")
        self.assertEqual(resources[0]["code"]["coding"][0]["code"], "54888009")

    def test_problem_author_name_and_id_fallback_are_mapped_to_recorder(self):
        section = {
            "entries": [
                {
                    "value": {"displayName": "Named problem"},
                    "effectiveDateTime": "2024-04-14",
                    "authorDisplay": "Family Medicine Physician Arzt",
                },
                {
                    "value": {"displayName": "ID-only problem"},
                    "effectiveDateTime": "2024-04-14",
                    "authorDisplay": "CDA author ID: 221381380 / 17332",
                },
            ]
        }

        resources = map_condition_section(section, "Patient/123", {})

        self.assertEqual(
            resources[0]["recorder"]["display"],
            "Family Medicine Physician Arzt",
        )
        self.assertEqual(
            resources[1]["recorder"]["display"],
            "CDA author ID: 221381380 / 17332",
        )

    def test_surgical_history_is_registered_for_procedure_mapping(self):
        mapper = get_section_mapper("10167-5")
        self.assertIs(mapper, map_procedure_section)

    def test_procedure_mapper_dedupes_identical_entries_with_shared_context(self):
        section = {
            "title": "Chirurgische Anamnese",
            "entries": [
                {
                    "id": {
                        "root": "1.2.3",
                        "extension": "A",
                    },
                    "code": {
                        "code": "123",
                        "displayName": "Proc A",
                        "codeSystem": "2.16.840.1.113883.6.96",
                    },
                    "effectiveDateTime": "2024-01-01",
                }
            ],
        }

        context = {}

        first = map_procedure_section(section, "Patient/123", context)
        second = map_procedure_section(section, "Patient/123", context)

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)

    def test_contacts_section_is_registered(self):
        mapper = get_section_mapper("46240-8")
        self.assertIsNone(mapper)

    def test_cda_completed_status_maps_to_fhir_finished(self):
        section = {
            "entries": [
                {
                    "type": "encounter",
                    "id": {"extension": "123"},
                    "statusCode": "completed",
                    "code": {"code": "AMB"},
                    "effectiveDateTime": "2025-12-18T09:00:00+01:00",
                }
            ]
        }

        resources = map_encounter_section(section, "Patient/123", {})

        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["status"], "finished")

    def test_lab_section_without_entries_uses_narrative_text(self):
        section = {
            "title": "Resultate",
            "code": {"code": "30954-2", "displayName": "Relevant diagnostic tests/laboratory data Narrative"},
            "entries": [],
            "narrativeText": "Wert 1: 5.2 mmol/l\nWert 2: normal",
        }

        resources = map_lab_section(section, "Patient/123", {})

        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["resourceType"], "DiagnosticReport")
        self.assertEqual(resources[0]["code"]["coding"][0]["code"], "30954-2")
        self.assertEqual(resources[0]["conclusion"], "Wert 1: 5.2 mmol/l\nWert 2: normal")

    def test_extract_sections_preserves_narrative_text_for_lab_sections(self):
        xml_payload = '''
        <ClinicalDocument xmlns="urn:hl7-org:v3">
            <component>
                <structuredBody>
                    <section>
                        <code code="30954-2" codeSystem="2.16.840.1.113883.6.1" displayName="Relevant diagnostic tests/laboratory data Narrative" />
                        <title>Resultate</title>
                        <text>Wert 1: 5.2 mmol/l\nWert 2: normal</text>
                    </section>
                </structuredBody>
            </component>
        </ClinicalDocument>
        '''

        root = ET.fromstring(xml_payload)
        sections = extract_sections(root)

        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["code"]["code"], "30954-2")
        self.assertEqual(sections[0]["narrativeText"], "Wert 1: 5.2 mmol/l\nWert 2: normal")
