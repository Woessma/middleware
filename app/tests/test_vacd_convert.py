import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


class VacdConvertEndpointTests(unittest.TestCase):
    def test_vacd_convert_endpoint_adds_vacd_meta_and_profile(self):
        sample_bundle = {
            "resourceType": "Bundle",
            "type": "transaction",
            "meta": {
                "tag": [
                    {"system": "http://woess.ch/cda-profile", "code": "EPIC-CCDA"}
                ]
            },
            "entry": [
                {
                    "resource": {
                        "resourceType": "Immunization",
                        "meta": {
                            "profile": [
                                "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-immunization"
                            ]
                        }
                    }
                }
            ],
        }

        with patch("main.cda_to_fhir_bundle", return_value=sample_bundle):
            client = TestClient(app)
            response = client.post(
                "/cda/vacd/convert",
                data={"raw_xml": "<ClinicalDocument />"},
            )

        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertNotIn("tag", payload["meta"])
        immunization = payload["entry"][0]["resource"]
        self.assertIn(
            "http://fhir.ch/ig/ch-vacd/StructureDefinition/ch-vacd-immunization",
            immunization["meta"]["profile"],
        )

    def test_vacd_convert_endpoint_uses_document_bundle_and_ch_vacd_profiles(self):
        sample_bundle = {
            "resourceType": "Bundle",
            "type": "transaction",
            "meta": {
                "tag": [
                    {"system": "http://woess.ch/cda-profile", "code": "EPIC-CCDA"}
                ]
            },
            "entry": [
                {
                    "resource": {
                        "resourceType": "Composition",
                        "meta": {"profile": ["http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-composition"]},
                    }
                },
                {
                    "resource": {
                        "resourceType": "Immunization",
                        "meta": {"profile": ["http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-immunization"]},
                    }
                },
            ],
        }

        with patch("main.cda_to_fhir_bundle", return_value=sample_bundle):
            client = TestClient(app)
            response = client.post(
                "/cda/vacd/convert",
                data={"raw_xml": "<ClinicalDocument />"},
            )

        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["type"], "document")
        self.assertIn(
            "http://fhir.ch/ig/ch-vacd/StructureDefinition/ch-vacd-document-immunization-administration",
            payload["meta"]["profile"],
        )
        self.assertEqual(payload["entry"][0]["resource"]["resourceType"], "Composition")
        self.assertIn(
            "http://fhir.ch/ig/ch-vacd/StructureDefinition/ch-vacd-composition-immunization-administration",
            payload["entry"][0]["resource"]["meta"]["profile"],
        )
        composition = payload["entry"][0]["resource"]
        self.assertEqual(
            composition["category"][0]["coding"][0]["display"],
            "CH VACD Immunization Administration",
        )
        self.assertEqual(
            composition["_confidentiality"]["extension"][0]["valueCodeableConcept"]["coding"][0]["code"],
            "17621005",
        )
        self.assertIn(
            "http://fhir.ch/ig/ch-vacd/StructureDefinition/ch-vacd-immunization",
            payload["entry"][1]["resource"]["meta"]["profile"],
        )

    def test_vacd_convert_endpoint_drops_unrelated_generic_resources(self):
        sample_bundle = {
            "resourceType": "Bundle",
            "type": "transaction",
            "entry": [
                {"resource": {"resourceType": "Composition", "section": [
                    {"title": "Impfungen", "code": {"coding": [{"system": "2.16.840.1.113883.6.1", "code": "11369-6"}]}},
                    {"title": "Soziale Anamnese", "code": {"coding": [{"system": "2.16.840.1.113883.6.1", "code": "29762-2"}]}},
                ]}},
                {"resource": {"resourceType": "Patient"}},
                {"resource": {"resourceType": "Immunization"}},
                {"resource": {"resourceType": "Observation"}},
                {"resource": {"resourceType": "CareTeam"}},
            ],
        }

        with patch("main.cda_to_fhir_bundle", return_value=sample_bundle):
            client = TestClient(app)
            response = client.post(
                "/cda/vacd/convert",
                data={"raw_xml": "<ClinicalDocument />"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        resource_types = [
            entry["resource"]["resourceType"]
            for entry in payload["entry"]
        ]
        self.assertNotIn("Observation", resource_types)
        self.assertNotIn("CareTeam", resource_types)
        self.assertEqual(len(payload["entry"][0]["resource"]["section"]), 1)
        self.assertEqual(
            payload["entry"][0]["resource"]["section"][0]["code"]["coding"][0]["code"],
            "11369-6",
        )

    def test_vacd_convert_endpoint_keeps_composition_references_resolvable(self):
        sample_bundle = {
            "resourceType": "Bundle",
            "type": "transaction",
            "entry": [
                {
                    "fullUrl": "urn:uuid:composition",
                    "resource": {
                        "resourceType": "Composition",
                        "subject": {"reference": "Patient/p1"},
                        "author": [{"reference": "Practitioner/missing"}],
                        "section": [],
                    },
                },
                {
                    "fullUrl": "urn:uuid:patient",
                    "resource": {"resourceType": "Patient", "id": "p1"},
                },
                {
                    "fullUrl": "urn:uuid:orphan",
                    "resource": {"resourceType": "PractitionerRole", "id": "role1"},
                },
            ],
        }

        with patch("main.cda_to_fhir_bundle", return_value=sample_bundle):
            client = TestClient(app)
            response = client.post(
                "/cda/vacd/convert",
                data={"raw_xml": "<ClinicalDocument />"},
            )

        self.assertEqual(response.status_code, 200)
        composition = response.json()["entry"][0]["resource"]
        self.assertEqual(
            composition["author"],
            [{"reference": "urn:uuid:patient"}],
        )


if __name__ == "__main__":
    unittest.main()
