import json
import unittest
from pathlib import Path

from services.epic_vacd_service import (
    build_vacd_source_bundle,
    is_epic_immunization_payload,
)

_SEARCHSET_PATH = Path(__file__).parent / "data" / "EPIC_Immunization.json"

_PATIENT = {
    "resourceType": "Patient",
    "id": "e63wRTbPfr1p8UW81d8Seiw3",
    "name": [{"family": "Mychart", "given": ["Theodore"]}],
    "gender": "male",
    "birthDate": "1948-07-07",
}


def _load_searchset():
    return json.loads(_SEARCHSET_PATH.read_text(encoding="utf-8"))


class EpicVacdServiceTests(unittest.TestCase):
    def test_payload_detection(self):
        self.assertTrue(is_epic_immunization_payload(_load_searchset()))
        self.assertTrue(
            is_epic_immunization_payload(
                {"patient": _PATIENT, "immunizations": _load_searchset()}
            )
        )
        self.assertFalse(
            is_epic_immunization_payload({"resourceType": "Bundle", "type": "document"})
        )

    def test_combined_payload_builds_document_source(self):
        bundle = build_vacd_source_bundle(
            {"patient": _PATIENT, "immunizations": _load_searchset()}
        )

        resources = [entry["resource"] for entry in bundle["entry"]]
        self.assertEqual(resources[0]["resourceType"], "Composition")
        self.assertEqual(resources[1]["resourceType"], "Patient")
        self.assertEqual(resources[2]["resourceType"], "Organization")
        # Custodian Organization is synthesized from the Epic location display.
        self.assertEqual(resources[2]["name"], "FHIR Sandbox")
        immunizations = [r for r in resources if r["resourceType"] == "Immunization"]
        # OperationOutcome from the searchset is dropped.
        self.assertEqual(len(immunizations), 4)
        self.assertEqual(len(resources), 7)

        composition = resources[0]
        self.assertEqual(
            composition["custodian"]["reference"],
            f"Organization/{resources[2]['id']}",
        )
        section = composition["section"][0]
        self.assertEqual(section["code"]["coding"][0]["code"], "11369-6")
        self.assertEqual(len(section["entry"]), 4)
        self.assertIn("Td", section["text"]["div"])

        patient_reference = f"Patient/{resources[1]['id']}"
        for immunization in immunizations:
            self.assertEqual(immunization["patient"]["reference"], patient_reference)

    def test_cvx_codes_get_display_and_snomed_twin(self):
        bundle = build_vacd_source_bundle(
            {"patient": _PATIENT, "immunizations": _load_searchset()}
        )
        immunizations = [
            entry["resource"]
            for entry in bundle["entry"]
            if entry["resource"]["resourceType"] == "Immunization"
        ]

        td = next(
            i for i in immunizations if i["vaccineCode"].get("text") == "Td"
        )
        codings = td["vaccineCode"]["coding"]
        cvx = next(c for c in codings if c["system"] == "http://hl7.org/fhir/sid/cvx")
        self.assertEqual(cvx["code"], "09")
        self.assertTrue(cvx["display"])
        self.assertIn(
            {"system": "http://snomed.info/sct", "code": "871826000", "display": "Td"},
            codings,
        )

        influenza = next(
            i for i in immunizations if "Influenza" in (i["vaccineCode"].get("text") or "")
        )
        self.assertTrue(
            any(
                c["system"] == "http://snomed.info/sct" and c["code"] == "346524008"
                for c in influenza["vaccineCode"]["coding"]
            )
        )
        # Epic-internal site/route codings are dropped, text survives.
        self.assertNotIn("coding", influenza.get("site", {}))
        self.assertTrue(influenza.get("site", {}).get("text"))

    def test_searchset_with_patient_entry_works(self):
        searchset = _load_searchset()
        searchset["entry"].append({"resource": dict(_PATIENT)})

        bundle = build_vacd_source_bundle(searchset)
        resource_types = [entry["resource"]["resourceType"] for entry in bundle["entry"]]
        self.assertEqual(resource_types[0], "Composition")
        self.assertIn("Patient", resource_types)
        self.assertEqual(resource_types.count("Immunization"), 4)

    def test_missing_patient_or_immunizations_raise(self):
        with self.assertRaises(ValueError):
            build_vacd_source_bundle(_load_searchset())
        with self.assertRaises(ValueError):
            build_vacd_source_bundle({"patient": _PATIENT, "immunizations": []})


if __name__ == "__main__":
    unittest.main()
