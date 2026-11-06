import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from services.fhir_validation_service import FhirValidationError

STRICT_PROFILE = (
    "http://fhir.ch/ig/ch-emed/StructureDefinition/ch-emed-medicationstatement"
)


def _sample_emediplan_payload():
    return json.dumps(
        {
            "Id": "plan-validate",
            "Patient": {"FName": "Max", "LName": "Muster", "BDt": "1980-01-01"},
            "Medicaments": [
                {
                    "Id": "7680123456789",
                    "IdType": 2,
                    "Pos": [{"DtFrom": "2026-07-01", "D": [1, 0, 1, 0]}],
                }
            ],
        }
    ).encode("utf-8")


class EmediplanValidateEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        patcher = patch("main._validate_bundle", side_effect=lambda bundle: bundle)
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("main.validate_fhir_bundle")
    def test_validate_adds_strict_ch_emed_profile_for_the_advisory_check(
        self, validate_fhir_bundle
    ):
        outcome = {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "information", "code": "informational"}],
        }
        validate_fhir_bundle.return_value = (200, outcome)

        response = self.client.post(
            "/emediplan/validate",
            content=_sample_emediplan_payload(),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), outcome)
        validated_bundle = validate_fhir_bundle.call_args.args[0]
        statements = [
            entry["resource"]
            for entry in validated_bundle["entry"]
            if entry["resource"]["resourceType"] == "MedicationStatement"
        ]
        self.assertTrue(statements)
        for statement in statements:
            self.assertIn(STRICT_PROFILE, statement["meta"]["profile"])

    @patch("main.validate_fhir_bundle")
    def test_validate_passes_through_profile_errors_without_blocking(
        self, validate_fhir_bundle
    ):
        outcome = {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": "structure"}],
        }
        validate_fhir_bundle.return_value = (422, outcome)

        response = self.client.post(
            "/emediplan/validate",
            content=_sample_emediplan_payload(),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), outcome)

    @patch("main.validate_fhir_bundle")
    def test_validate_reports_unavailable_internal_validator(
        self, validate_fhir_bundle
    ):
        validate_fhir_bundle.side_effect = FhirValidationError(
            "Internal FHIR validator unavailable"
        )

        response = self.client.post(
            "/emediplan/validate",
            content=_sample_emediplan_payload(),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 502)
        outcome = response.json()
        self.assertEqual(outcome["resourceType"], "OperationOutcome")
        self.assertEqual(outcome["issue"][0]["severity"], "error")

    @patch("main.validate_fhir_bundle")
    def test_validate_accepts_qr_pdf_and_image_uploads(self, validate_fhir_bundle):
        import base64
        import gzip
        import io

        import pymupdf
        import qrcode

        outcome = {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "information", "code": "informational"}],
        }
        validate_fhir_bundle.return_value = (200, outcome)

        chmed = b"CHMED16A1" + base64.b64encode(
            gzip.compress(_sample_emediplan_payload())
        )
        qr_image = qrcode.make(chmed.decode("ascii")).convert("RGB")
        png_buffer = io.BytesIO()
        qr_image.save(png_buffer, format="PNG")
        document = pymupdf.open()
        page = document.new_page()
        page.insert_image(page.rect, stream=png_buffer.getvalue())
        pdf_bytes = document.tobytes()
        document.close()

        for name, content, content_type in (
            ("plan.pdf", pdf_bytes, "application/pdf"),
            ("plan.png", png_buffer.getvalue(), "image/png"),
        ):
            with self.subTest(name=name):
                response = self.client.post(
                    "/emediplan/validate",
                    files={"file": (name, content, content_type)},
                )

                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json(), outcome)
                validated_bundle = validate_fhir_bundle.call_args.args[0]
                statements = [
                    entry["resource"]
                    for entry in validated_bundle["entry"]
                    if entry["resource"]["resourceType"] == "MedicationStatement"
                ]
                self.assertTrue(statements)
                for statement in statements:
                    self.assertIn(STRICT_PROFILE, statement["meta"]["profile"])

    def test_validate_rejects_empty_payload(self):
        response = self.client.post("/emediplan/validate")

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
