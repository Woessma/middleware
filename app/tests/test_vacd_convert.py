import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app, _mark_vacd_bundle
from fhir.bundle import build_bundle_entry


class VacdConvertEndpointTests(unittest.TestCase):
    def test_vacd_profiles_and_missing_data_do_not_claim_clinical_verification(self):
        verification_url = (
            "http://fhir.ch/ig/ch-vacd/StructureDefinition/"
            "ch-vacd-ext-verification-status"
        )
        confirmed = {
            "url": verification_url,
            "valueCoding": {"system": "http://snomed.info/sct", "code": "59156000"},
        }
        source = {
            "entry": [
                {"resource": {
                    "resourceType": "Composition", "id": "composition",
                    "meta": {"profile": [
                        "http://fhir.ch/ig/ch-ips/StructureDefinition/ch-ips-composition"
                    ]},
                }},
                {"resource": {
                    "resourceType": "Patient", "id": "patient",
                    "contact": [
                        {"relationship": [{"coding": [{"code": "C"}]}]},
                        {"relationship": [{"coding": [{"code": "C"}]}],
                         "address": {"city": "Synthetic City"}},
                        {"relationship": [{"coding": [{"code": "MTH"}]}]},
                    ],
                }},
                {"resource": {"resourceType": "Immunization", "id": "unverified"}},
                {"resource": {
                    "resourceType": "Immunization", "id": "verified",
                    "extension": [confirmed],
                }},
            ]
        }
        bundle = _mark_vacd_bundle(source)
        composition, patient, unverified, verified = [
            entry["resource"] for entry in bundle["entry"]
        ]
        self.assertNotIn(
            "http://fhir.ch/ig/ch-ips/StructureDefinition/ch-ips-composition",
            composition["meta"]["profile"],
        )
        for field in ("city", "postalCode", "country"):
            self.assertEqual(
                patient["contact"][0]["address"][f"_{field}"]["extension"][0]["valueCode"],
                "unknown",
            )
        self.assertEqual(patient["contact"][1]["address"]["city"], "Synthetic City")
        self.assertNotIn("_city", patient["contact"][1]["address"])
        self.assertNotIn("address", patient["contact"][2])
        self.assertEqual(unverified["extension"][0]["valueCoding"]["code"], "76104008")
        self.assertEqual(verified["extension"], [confirmed])
        _mark_vacd_bundle(bundle)
        self.assertEqual(len(unverified["extension"]), 1)

    def test_vacd_document_keeps_full_urls_and_resolves_local_references(self):
        source = {
            "resourceType": "Bundle",
            "type": "transaction",
            "entry": [
                build_bundle_entry({
                    "resourceType": "Patient", "id": "synthetic-patient",
                }),
                build_bundle_entry({
                    "resourceType": "Composition", "id": "synthetic-composition",
                    "subject": {"reference": "Patient/synthetic-patient"},
                }),
                build_bundle_entry({
                    "resourceType": "Immunization", "id": "synthetic-immunization",
                    "patient": {"reference": "Patient/synthetic-patient"},
                }),
            ],
        }
        with (
            patch("main.cda_to_fhir_bundle", return_value=source),
            patch("main._validate_bundle", side_effect=lambda bundle: bundle),
        ):
            response = TestClient(app).post(
                "/cda/vacd/convert", content=b"<ClinicalDocument />"
            )
        self.assertEqual(response.status_code, 200, response.text)
        bundle = response.json()
        self.assertEqual(bundle["type"], "document")
        self.assertTrue(bundle["identifier"]["value"].startswith("urn:uuid:"))
        self.assertIn("timestamp", bundle)
        self.assertEqual(bundle["entry"][0]["resource"]["resourceType"], "Composition")
        urls = {entry["fullUrl"] for entry in bundle["entry"]}
        self.assertEqual(len(urls), len(bundle["entry"]))
        patient_url = next(
            entry["fullUrl"] for entry in bundle["entry"]
            if entry["resource"]["resourceType"] == "Patient"
        )
        self.assertEqual(bundle["entry"][0]["resource"]["subject"]["reference"], patient_url)
        immunization = next(
            entry["resource"] for entry in bundle["entry"]
            if entry["resource"]["resourceType"] == "Immunization"
        )
        self.assertEqual(immunization["patient"]["reference"], patient_url)
        for entry in bundle["entry"]:
            self.assertNotIn("request", entry)

    def test_vacd_prepare_is_disabled_without_conversion_or_write(self):
        with (
            patch("main.cda_to_fhir_bundle") as convert,
            patch("main._stabilize_bundle") as stabilize,
            patch("main.requests.post") as post,
        ):
            response = TestClient(app).post(
                "/cda/vacd/prepare",
                content=b"<ClinicalDocument />",
                headers={"Authorization": "Bearer synthetic-test-token"},
            )
        self.assertEqual(response.status_code, 410, response.text)
        self.assertEqual(response.json()["resourceType"], "OperationOutcome")
        convert.assert_not_called()
        stabilize.assert_not_called()
        post.assert_not_called()

    def test_vacd_prepare_is_disabled_even_without_bearer(self):
        with patch("main.cda_to_fhir_bundle") as convert:
            response = TestClient(app).post("/cda/vacd/prepare", content=b"<ClinicalDocument />")
        self.assertEqual(response.status_code, 410)
        convert.assert_not_called()

    def test_vacd_send_keeps_document_format_and_returns_send_report(self):
        source = {
            "resourceType": "Bundle",
            "entry": [
                {"resource": {"resourceType": "Composition", "id": "test-composition"}},
                {"resource": {"resourceType": "Patient", "id": "test-patient"}},
            ],
        }
        with (
            patch("main.cda_to_fhir_bundle", return_value=source),
            patch("main._validate_bundle", side_effect=lambda bundle: bundle),
            patch("main.send_vacd_bundle", return_value={"status": "sent"}) as send,
        ):
            response = TestClient(app).post(
                "/cda/vacd/send",
                params={"destination_base_url": "https://vacd.example/fhir"},
                content=b"<ClinicalDocument />",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["send"]["status"], "sent")
        self.assertEqual(send.call_args.kwargs["bundle"]["type"], "document")
        self.assertEqual(send.call_args.kwargs["destination_base_url"], "https://vacd.example/fhir")

    def test_vacd_convert_endpoint_adds_vacd_meta_and_profile(self):
        sample_bundle = {
            "resourceType": "Bundle",
            "type": "transaction",
            "meta": {
                "tag": [
                    {"system": "https://fhir.omnilink.ch/cda-profile", "code": "EPIC-CCDA"}
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
                    {"system": "https://fhir.omnilink.ch/cda-profile", "code": "EPIC-CCDA"}
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

    def test_epic_fhir_bundle_converts_to_vacd_and_validates_without_writing(self):
        source = {
            "resourceType": "Bundle",
            "type": "document",
            "meta": {"tag": [{"system": "https://example.test", "code": "epic"}]},
            "entry": [
                {
                    "fullUrl": "urn:uuid:composition",
                    "resource": {
                        "resourceType": "Composition",
                        "id": "composition",
                        "meta": {"profile": [
                            "http://fhir.ch/ig/ch-ips/StructureDefinition/ch-ips-composition"
                        ]},
                        "subject": {"reference": "Patient/patient"},
                        "section": [{
                            "title": "Immunizations",
                            "code": {"coding": [{
                                "system": "http://loinc.org",
                                "code": "11369-6",
                            }]},
                            "entry": [{"reference": "Immunization/immunization"}],
                        }],
                    },
                },
                {
                    "fullUrl": "urn:uuid:patient",
                    "resource": {"resourceType": "Patient", "id": "patient"},
                },
                {
                    "fullUrl": "urn:uuid:immunization",
                    "resource": {
                        "resourceType": "Immunization",
                        "id": "immunization",
                        "patient": {"reference": "Patient/patient"},
                    },
                },
                {
                    "fullUrl": "urn:uuid:observation",
                    "resource": {"resourceType": "Observation", "id": "observation"},
                },
            ],
        }

        outcome = {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "information", "code": "informational"}],
        }
        with (
            patch("main._validate_bundle", side_effect=lambda bundle: bundle) as terminology,
            patch("main.validate_fhir_bundle", return_value=(200, outcome)) as validate,
            patch("main.requests.post") as post,
        ):
            response = TestClient(app).post("/fhir/vacd/convert", json=source)

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        bundle = result["bundle"]
        self.assertEqual(result["validation"], outcome)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(bundle["type"], "document")
        self.assertNotIn("tag", bundle["meta"])
        self.assertIn(
            "http://fhir.ch/ig/ch-vacd/StructureDefinition/"
            "ch-vacd-document-immunization-administration",
            bundle["meta"]["profile"],
        )
        self.assertEqual(
            [entry["resource"]["resourceType"] for entry in bundle["entry"]],
            ["Composition", "Patient", "Immunization"],
        )
        immunization = bundle["entry"][2]["resource"]
        self.assertEqual(
            immunization["extension"][0]["valueCoding"]["code"],
            "76104008",
        )
        terminology.assert_called_once()
        validate.assert_called_once()
        self.assertEqual(
            validate.call_args.args[0]["entry"][0]["resource"]["resourceType"],
            "Composition",
        )
        post.assert_not_called()

    def test_fhir_vacd_convert_rejects_bundle_without_required_resources(self):
        client = TestClient(app)
        for entries in ([], [None]):
            with self.subTest(entries=entries):
                response = client.post(
                    "/fhir/vacd/convert",
                    json={"resourceType": "Bundle", "entry": entries},
                )

                self.assertEqual(response.status_code, 400)
                expected = "entry must contain a resource" if entries else "Composition, Patient"
                self.assertIn(expected, response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
