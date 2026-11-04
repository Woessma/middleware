import base64
import gzip
import json
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from main import (
    BRIDGELINK_EMEDIPLAN_IMPORT_URL,
    _prepare_emediplan_import_bundle as app_module_prepare,
    app,
)
from services.fhir_duplicate_service import (
    FhirDuplicateLookupError,
    FhirResourceMatchConflictError,
)
from services.patient_service import (
    PatientLookupError,
    PatientMatchConflictError,
    find_matching_patient,
)


class EmediplanBridgeLinkImportTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.authorization = "Bearer test-token"
        self.bundle = {
            "resourceType": "Bundle",
            "type": "transaction",
            "entry": [],
        }
        for target in (
            "main.find_matching_patient",
            "main.find_patient_by_id",
            "main.find_existing_resource_by_identifier",
        ):
            patcher = patch(target, return_value=None)
            patcher.start()
            self.addCleanup(patcher.stop)

    def upstream_response(self):
        upstream = Mock()
        upstream.status_code = 200
        upstream.content = b'{"resourceType":"Bundle","type":"transaction-response"}'
        upstream.headers = {"Content-Type": "application/fhir+json"}
        return upstream

    @patch("main.requests.post")
    @patch("main._validate_bundle", side_effect=lambda bundle: bundle)
    def test_prepare_accepts_raw_and_encoded_emediplan_without_bridge_callback(
        self, validate_bundle, post
    ):
        source = {
            "Id": "test-plan",
            "Patient": {"FName": "Test", "LName": "Example", "BDt": "1980-01-01"},
            "Medicaments": [],
        }
        source_json = json.dumps(source).encode("utf-8")
        encoded = base64.b64encode(gzip.compress(source_json))
        for payload in (source_json, b"CHMED16A0" + source_json, b"CHMED16A1" + encoded):
            with self.subTest(payload=payload[:20]):
                response = self.client.post(
                    "/emediplan/prepare",
                    content=payload,
                    headers={"Authorization": self.authorization},
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["type"], "transaction")
                self.assertTrue(response.json()["entry"])
        post.assert_not_called()

    @patch("main.requests.post")
    @patch("main._prepare_emediplan_import_bundle")
    @patch("main.emediplan_to_fhir_bundle")
    def test_prepare_accepts_fhir_without_emediplan_conversion(
        self, convert, prepare, post
    ):
        prepare.return_value = self.bundle
        for source in (self.bundle, {"resourceType": "Patient", "id": "test-patient"}):
            with self.subTest(resource_type=source["resourceType"]):
                response = self.client.post(
                    "/emediplan/prepare",
                    json=source,
                    headers={"Authorization": self.authorization},
                )
                self.assertEqual(response.status_code, 200)
                prepare.assert_called_with(source)
        convert.assert_not_called()
        post.assert_not_called()

    @patch("main.requests.post")
    @patch("main._prepare_emediplan_import_bundle")
    @patch("main.resolve_emediplan_payload", return_value=b'{"Medicaments":[]}')
    @patch("main.emediplan_to_fhir_bundle")
    def test_prepare_accepts_qr_image_and_multipart(
        self, convert, resolve, prepare, post
    ):
        convert.return_value = self.bundle
        prepare.return_value = self.bundle
        headers = {"Authorization": self.authorization}
        response = self.client.post(
            "/emediplan/prepare",
            content=b"image bytes",
            headers={**headers, "Content-Type": "image/png"},
        )
        self.assertEqual(response.status_code, 200)
        resolve.assert_called_with(b"image bytes", "image/png")
        response = self.client.post(
            "/emediplan/prepare",
            files={"file": ("plan.png", b"image bytes", "image/png")},
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        resolve.assert_called_with(b"image bytes", "image/png")
        prepare.assert_called_with(self.bundle)
        post.assert_not_called()

    @patch("main.requests.post")
    @patch("main._prepare_emediplan_import_bundle")
    def test_prepare_maps_preflight_errors(self, prepare, post):
        for error, expected in (
            (PatientMatchConflictError("ambiguous"), 409),
            (FhirResourceMatchConflictError("ambiguous"), 409),
            (PatientLookupError("unavailable"), 502),
            (FhirDuplicateLookupError("unavailable"), 502),
        ):
            with self.subTest(error=type(error).__name__):
                prepare.side_effect = error
                response = self.client.post(
                    "/emediplan/prepare",
                    json=self.bundle,
                    headers={"Authorization": self.authorization},
                )
                self.assertEqual(response.status_code, expected)
        post.assert_not_called()

    @patch("main.requests.post")
    @patch("main.resolve_emediplan_payload")
    def test_prepare_requires_bearer(self, resolve, post):
        response = self.client.post("/emediplan/prepare", json=self.bundle)
        self.assertEqual(response.status_code, 401)
        resolve.assert_not_called()
        post.assert_not_called()

    @patch("main.requests.post")
    def test_prepare_rejects_empty_and_invalid_payloads(self, post):
        for payload in (b"", b"{invalid", b"CHMED16A1invalid"):
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/emediplan/prepare",
                    content=payload,
                    headers={"Authorization": self.authorization},
                )
                self.assertEqual(response.status_code, 400, response.text)
        post.assert_not_called()

    @patch("main.requests.post")
    @patch("main._validate_bundle")
    @patch("main.emediplan_to_fhir_bundle")
    @patch("main.resolve_emediplan_payload")
    def test_import_converts_and_forwards_fhir_json(
        self,
        resolve_payload,
        convert_payload,
        validate_bundle,
        post,
    ):
        resolve_payload.return_value = {"Medicaments": []}
        convert_payload.return_value = self.bundle
        validate_bundle.return_value = self.bundle
        post.return_value = self.upstream_response()

        response = self.client.post(
            "/emediplan/import",
            content=b'{"Medicaments":[]}',
            headers={
                "Authorization": self.authorization,
                "Content-Type": "application/json",
                "Accept": "application/fhir+json",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["type"], "transaction-response")
        post.assert_called_once_with(
            BRIDGELINK_EMEDIPLAN_IMPORT_URL,
            data=json.dumps(self.bundle).encode("utf-8"),
            headers={
                "Authorization": self.authorization,
                "Accept": "application/fhir+json",
                "Content-Type": "application/fhir+json",
            },
            timeout=300,
        )

    @patch("main.requests.post")
    @patch("main._validate_bundle")
    @patch("main.emediplan_to_fhir_bundle")
    @patch("main.extract_emediplan_payload_from_file")
    def test_qr_import_converts_and_forwards_fhir_json(
        self,
        extract_payload,
        convert_payload,
        validate_bundle,
        post,
    ):
        extract_payload.return_value = {"Medicaments": []}
        convert_payload.return_value = self.bundle
        validate_bundle.return_value = self.bundle
        post.return_value = self.upstream_response()

        response = self.client.post(
            "/emediplan/qr/import",
            content=b"pdf bytes",
            headers={
                "Authorization": self.authorization,
                "Content-Type": "application/pdf",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["type"], "transaction-response")
        post.assert_called_once_with(
            BRIDGELINK_EMEDIPLAN_IMPORT_URL,
            data=json.dumps(self.bundle).encode("utf-8"),
            headers={
                "Authorization": self.authorization,
                "Accept": "*/*",
                "Content-Type": "application/fhir+json",
            },
            timeout=300,
        )

    @patch("main.requests.post")
    @patch("main._validate_bundle")
    def test_bundle_import_forwards_validated_fhir_json(self, validate_bundle, post):
        validate_bundle.return_value = self.bundle
        post.return_value = self.upstream_response()

        response = self.client.post(
            "/emediplan/import-bundle",
            json=self.bundle,
            headers={"Authorization": self.authorization},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["type"], "transaction-response")
        post.assert_called_once_with(
            BRIDGELINK_EMEDIPLAN_IMPORT_URL,
            data=json.dumps(self.bundle).encode("utf-8"),
            headers={
                "Authorization": self.authorization,
                "Accept": "*/*",
                "Content-Type": "application/fhir+json",
            },
            timeout=300,
        )

    @patch("main.requests.post")
    @patch("main.resolve_emediplan_payload")
    def test_import_rejects_missing_bearer_before_conversion(self, resolve_payload, post):
        response = self.client.post(
            "/emediplan/import",
            content=b'{"Medicaments":[]}',
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 401)
        resolve_payload.assert_not_called()
        post.assert_not_called()

    def test_import_bundle_reuses_existing_patient_and_resources(self):
        source_bundle = {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": "patient-from-source",
                        "identifier": [
                            {"system": "urn:test:patient", "value": "patient-1"}
                        ],
                    }
                },
                {
                    "resource": {
                        "resourceType": "Medication",
                        "id": "medication-from-source",
                        "identifier": [
                            {"system": "urn:test:medication", "value": "drug-1"}
                        ],
                    }
                },
                {
                    "resource": {
                        "resourceType": "MedicationStatement",
                        "id": "statement-from-source",
                        "identifier": [
                            {"system": "urn:test:statement", "value": "statement-1"}
                        ],
                        "subject": {"reference": "Patient/patient-from-source"},
                        "medicationReference": {
                            "reference": "Medication/medication-from-source"
                        },
                    }
                },
            ],
        }

        def find_existing(resource):
            return {
                "id": {
                    "Medication": "medication-existing",
                    "MedicationStatement": "statement-existing",
                }[resource["resourceType"]]
            }

        with (
            patch("main.enrich_emediplan_bundle", side_effect=lambda value: value),
            patch(
                "main.find_matching_patient",
                return_value={"resourceType": "Patient", "id": "patient-existing"},
            ),
            patch(
                "main.find_existing_resource_by_identifier",
                side_effect=find_existing,
            ),
            patch(
                "main.find_patient_by_id",
                return_value={"resourceType": "Patient", "id": "patient-existing"},
            ),
            patch("main._validate_bundle", side_effect=lambda value: value),
        ):
            result = app_module_prepare(source_bundle)

        self.assertEqual(result["type"], "transaction")
        resources = {
            entry["resource"]["resourceType"]: entry
            for entry in result["entry"]
        }
        self.assertNotIn("Patient", resources)
        self.assertEqual(resources["Medication"]["resource"]["id"], "medication-existing")
        self.assertEqual(
            resources["MedicationStatement"]["resource"]["id"],
            "statement-existing",
        )
        self.assertEqual(
            resources["MedicationStatement"]["resource"]["subject"]["reference"],
            "Patient/patient-existing",
        )
        self.assertEqual(
            resources["MedicationStatement"]["resource"]["medicationReference"]["reference"],
            "Medication/medication-existing",
        )
        self.assertEqual(
            resources["Medication"]["request"],
            {"method": "PUT", "url": "Medication/medication-existing"},
        )

    @patch("services.patient_service.requests.get")
    def test_patient_check_matches_existing_identifier(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "resourceType": "Bundle",
            "total": 1,
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": "patient-existing",
                    }
                }
            ],
        }
        get.return_value = response

        patient = find_matching_patient(
            {
                "resourceType": "Patient",
                "identifier": [
                    {"system": "urn:test:patient", "value": "patient-1"}
                ],
            }
        )

        self.assertEqual(patient["id"], "patient-existing")
        self.assertEqual(
            get.call_args.kwargs["params"]["identifier"],
            "urn:test:patient|patient-1",
        )

    @patch("services.patient_service.requests.get")
    def test_patient_check_falls_back_to_name_and_birth_date(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "resourceType": "Bundle",
            "total": 1,
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": "patient-existing",
                        "birthDate": "1980-01-01",
                        "name": [{"family": "Muster", "given": ["Max"]}],
                    }
                }
            ],
        }
        get.return_value = response

        patient = find_matching_patient(
            {
                "resourceType": "Patient",
                "birthDate": "1980-01-01",
                "name": [{"family": "Muster", "given": ["Max"]}],
            }
        )

        self.assertEqual(patient["id"], "patient-existing")
        self.assertEqual(
            get.call_args.kwargs["params"],
            {
                "family": "Muster",
                "given": "Max",
                "birthdate": "1980-01-01",
                "_count": "2",
            },
        )


if __name__ == "__main__":
    unittest.main()
