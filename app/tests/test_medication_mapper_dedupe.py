import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from mappers.medication_mapper import map_medication_section
from parser.cda.section_parser import extract_sections


class MedicationMapperDedupeTests(unittest.TestCase):
    def test_prefers_dated_entry_over_same_entry_without_date(self):
        section = {
            "entries": [
                {
                    "effectiveTime": "20250501",
                    "statusCode": "active",
                    "dosageText": "1-0-0-0",
                    "consumable": {
                        "code": {
                            "displayName": "Ramipril 1.25 mg",
                        }
                    },
                },
                {
                    "statusCode": "active",
                    "dosageText": "1-0-0-0",
                    "consumable": {
                        "code": {
                            "displayName": "Ramipril 1.25 mg",
                        }
                    },
                },
            ]
        }

        resources = map_medication_section(
            section,
            patient_reference="Patient/3192",
            context={},
        )

        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0].get("effectiveDateTime"), "2025-05-01")

    def test_epic_medication_section_maps_dosage_and_instruction_notes(self):
        epic_path = Path(__file__).parent / "data" / "CDA-EPIC.xml"
        root = ET.parse(epic_path).getroot()
        sections = extract_sections(root)
        medication_section = next(
            section
            for section in sections
            if section["code"]["code"] == "10160-0"
        )

        resources = map_medication_section(
            medication_section,
            patient_reference="Patient/123",
            context={},
        )

        self.assertEqual(len(resources), 1)

        medication = resources[0]
        dosage = medication["dosage"][0]

        self.assertEqual(dosage["text"], "Einnahme: 1 Tablette (1.25 mg) 1 mal täglich morgens [1-0-0-0]")
        self.assertEqual(dosage["doseAndRate"][0]["doseQuantity"], {"value": "1.25", "unit": "mg"})
        self.assertTrue(medication["note"])
        self.assertIn(
            "Einnahme: 1 Tablette (1.25 mg) 1 mal täglich morgens [1-0-0-0]",
            {item["text"] for item in medication["note"]},
        )

        coding_pairs = {
            (item.get("system"), item.get("code"))
            for item in medication.get("medicationCodeableConcept", {}).get("coding", [])
        }
        self.assertIn(("http://snomed.info/sct", "410942007"), coding_pairs)


if __name__ == "__main__":
    unittest.main()
