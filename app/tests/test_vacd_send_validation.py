import copy
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from main import app
from services.fhir_validation_service import FhirValidationError
from services.vacd_send_service import (
    VACD_DOCUMENT_PROFILE,
    VacdValidationRejected,
    send_vacd_bundle,
)


def outcome(severity):
    return {
        "resourceType": "OperationOutcome",
        "issue": [{"severity": severity, "code": "processing", "diagnostics": "Synthetic"}],
    }


def document():
    return {
        "resourceType": "Bundle",
        "type": "document",
        "meta": {"profile": [VACD_DOCUMENT_PROFILE]},
        "entry": [
            {"fullUrl": "urn:uuid:composition", "resource": {
                "resourceType": "Composition", "id": "composition",
                "subject": {"reference": "urn:uuid:patient"},
                "author": [{"reference": "urn:uuid:author"}],
                "custodian": {"reference": "urn:uuid:organization"},
            }},
            {"fullUrl": "urn:uuid:patient", "resource": {
                "resourceType": "Patient", "id": "patient",
            }},
            {"fullUrl": "urn:uuid:author", "resource": {
                "resourceType": "Practitioner", "id": "author",
            }},
            {"fullUrl": "urn:uuid:organization", "resource": {
                "resourceType": "Organization", "id": "organization",
            }},
            {"fullUrl": "urn:uuid:immunization", "resource": {
                "resourceType": "Immunization", "id": "immunization",
                "patient": {"reference": "Patient/patient"},
            }},
        ],
    }


class VacdSendValidationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch("services.vacd_send_service.VACD_IMPORT_DB", directory.name + "/imports.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        search = patch("services.vacd_send_service.requests.get", return_value=Mock(
            status_code=200,
            json=lambda: {"resourceType": "Bundle", "type": "searchset", "total": 0},
        ))
        search.start()
        self.addCleanup(search.stop)

    def test_preflight_error_fatal_or_input_rejection_never_contacts_destination(self):
        for status, severity in ((200, "error"), (200, "fatal"), (400, "error"), (422, "error")):
            with (
                self.subTest(status=status, severity=severity),
                patch("services.vacd_send_service.validate_fhir_bundle",
                      return_value=(status, outcome(severity))),
                patch("services.vacd_send_service.create_or_find_vacd_patient") as patient,
                patch("services.vacd_send_service.requests.post") as post,
            ):
                with self.assertRaises(VacdValidationRejected) as rejected:
                    send_vacd_bundle(document(), "https://target.invalid/fhir")
                self.assertEqual(rejected.exception.phase, "before-patient")
                patient.assert_not_called()
                post.assert_not_called()

    def test_preflight_outage_never_contacts_destination(self):
        with (
            patch("services.vacd_send_service.validate_fhir_bundle",
                  side_effect=FhirValidationError("Unavailable")),
            patch("services.vacd_send_service.create_or_find_vacd_patient") as patient,
            patch("services.vacd_send_service.requests.post") as post,
        ):
            with self.assertRaises(FhirValidationError):
                send_vacd_bundle(document(), "https://target.invalid/fhir")
        patient.assert_not_called()
        post.assert_not_called()

    def test_missing_vacd_profile_never_contacts_destination(self):
        bundle = document()
        bundle["meta"]["profile"] = []
        with (
            patch("services.vacd_send_service.validate_fhir_bundle") as validate,
            patch("services.vacd_send_service.create_or_find_vacd_patient") as patient,
        ):
            with self.assertRaises(VacdValidationRejected):
                send_vacd_bundle(bundle, "https://target.invalid/fhir")
        validate.assert_not_called()
        patient.assert_not_called()

    def test_final_error_or_outage_blocks_document_after_patient_step(self):
        for failure in ((200, outcome("error")), FhirValidationError("Unavailable")):
            with (
                self.subTest(failure=failure),
                patch("services.vacd_send_service.validate_fhir_bundle",
                      side_effect=[(200, outcome("information")), failure]) as validate,
                patch("services.vacd_send_service.create_or_find_vacd_patient",
                      return_value=({"id": "target-patient"}, False)) as patient,
                patch("services.vacd_send_service.requests.post") as post,
            ):
                with self.assertRaises((VacdValidationRejected, FhirValidationError)):
                    send_vacd_bundle(document(), "https://target.invalid/fhir")
                self.assertEqual(validate.call_count, 2)
                patient.assert_called_once()
                post.assert_not_called()

    def test_success_validates_exact_outbound_payload_preserving_authorship(self):
        events = []
        validated = []

        def validate(bundle):
            events.append("validate")
            validated.append(copy.deepcopy(bundle))
            return 200, outcome("warning")

        def patient(*args, **kwargs):
            events.append("patient")
            return {"id": "target-patient"}, True

        def post(url, **kwargs):
            events.append("send")
            self.assertEqual(kwargs["json"], validated[1])
            self.assertEqual(url, "https://target.invalid/fhir/Bundle")
            return Mock(status_code=201, json=lambda: {"resourceType": "Bundle"})

        with (
            patch("services.vacd_send_service.validate_fhir_bundle", side_effect=validate),
            patch("services.vacd_send_service.create_or_find_vacd_patient", side_effect=patient),
            patch("services.vacd_send_service.requests.post", side_effect=post),
        ):
            report = send_vacd_bundle(document(), "https://target.invalid/fhir")
        self.assertEqual(events, ["validate", "patient", "validate", "send"])
        self.assertEqual(report["status"], "sent")
        self.assertEqual(report["validation"]["before_bundle"], outcome("warning"))
        composition = validated[1]["entry"][0]["resource"]
        self.assertEqual(composition["subject"]["reference"], "Patient/target-patient")
        self.assertEqual(composition["author"][0]["reference"], "Practitioner/author")
        self.assertEqual(composition["custodian"]["reference"], "Organization/organization")
        self.assertEqual(
            validated[1]["entry"][4]["resource"]["patient"]["reference"],
            "Patient/target-patient",
        )

    def test_endpoint_returns_blocking_outcome_instead_of_success(self):
        for exception, status in (
            (VacdValidationRejected(outcome("error"), "before-patient"), 422),
            (FhirValidationError("Internal FHIR validator unavailable"), 502),
        ):
            with (
                self.subTest(status=status),
                patch("main.cda_to_fhir_bundle", return_value=document()),
                patch("main._embed_precreated_resource"),
                patch("main._validate_bundle", side_effect=lambda bundle: bundle),
                patch("main.send_vacd_bundle", side_effect=exception),
            ):
                response = TestClient(app).post(
                    "/cda/vacd/send", content=b"<ClinicalDocument/>",
                    params={"destination_base_url": "https://target.invalid/fhir"},
                )
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["resourceType"], "OperationOutcome")
            self.assertEqual(response.json()["issue"][0]["severity"], "error")
