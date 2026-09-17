import unittest
from unittest.mock import Mock, patch

from services.terminology_service import (
    call_terminology_operation,
    enrich_bundle_terminology,
    validate_bundle_terminology,
    validate_coding,
)


class TerminologyServiceTests(unittest.TestCase):
    @patch("services.terminology_service.validate_coding")
    def test_validates_each_bundle_coding_only_once(self, mock_validate):
        mock_validate.return_value = {"status": "validated", "result": {}}
        bundle = {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "code": {
                            "coding": [
                                {"system": "http://snomed.info/sct", "code": "123"},
                                {"system": "http://snomed.info/sct", "code": "123"},
                            ]
                        }
                    }
                }
            ],
        }

        report = validate_bundle_terminology(bundle)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["checked"], 1)
        mock_validate.assert_called_once()

    @patch("services.terminology_service.requests.post")
    def test_enriches_missing_display_from_tx_lookup(self, mock_post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "resourceType": "Parameters",
            "parameter": [
                {"name": "display", "valueString": "Systolic blood pressure"}
            ],
        }
        mock_post.return_value = response
        bundle = {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Observation",
                        "code": {
                            "coding": [
                                {"system": "http://loinc.org", "code": "8480-6"}
                            ]
                        },
                    }
                }
            ],
        }

        report = enrich_bundle_terminology(bundle, base_url="https://tx.fhir.ch/r4")

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["enriched"], 1)
        self.assertEqual(
            bundle["entry"][0]["resource"]["code"]["coding"][0]["display"],
            "Systolic blood pressure",
        )
        self.assertEqual(
            mock_post.call_args.args[0],
            "https://tx.fhir.ch/r4/CodeSystem/$lookup",
        )

    @patch("services.terminology_service.requests.post")
    def test_enrichment_reuses_cached_lookup_display(self, mock_post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "resourceType": "Parameters",
            "parameter": [
                {"name": "display", "valueString": "Glucose"}
            ],
        }
        mock_post.return_value = response
        bundle = {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Observation",
                        "code": {
                            "coding": [
                                {"system": "http://loinc.org", "code": "2345-7"}
                            ]
                        },
                    }
                },
                {
                    "resource": {
                        "resourceType": "Observation",
                        "code": {
                            "coding": [
                                {"system": "http://loinc.org", "code": "2345-7"}
                            ]
                        },
                    }
                },
            ],
        }

        report = enrich_bundle_terminology(bundle, base_url="https://tx.fhir.ch/r4")

        self.assertEqual(report["enriched"], 2)
        mock_post.assert_called_once()

    @patch("services.terminology_service.requests.post")
    def test_enrichment_does_not_overwrite_existing_display(self, mock_post):
        bundle = {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Observation",
                        "code": {
                            "coding": [
                                {
                                    "system": "http://loinc.org",
                                    "code": "8480-6",
                                    "display": "Existing display",
                                }
                            ]
                        },
                    }
                }
            ],
        }

        report = enrich_bundle_terminology(bundle)

        self.assertEqual(report["enriched"], 0)
        self.assertEqual(
            bundle["entry"][0]["resource"]["code"]["coding"][0]["display"],
            "Existing display",
        )
        mock_post.assert_not_called()

    @patch("services.terminology_service.requests.post")
    def test_supports_conceptmap_translate_operation(self, mock_post):
        response = Mock()
        response.raise_for_status.return_value = None
        mock_post.return_value = response

        call_terminology_operation(
            "ConceptMap",
            "$translate",
            {"resourceType": "Parameters"},
            base_url="https://tx.fhir.ch/r4",
        )

        self.assertEqual(
            mock_post.call_args.args[0],
            "https://tx.fhir.ch/r4/ConceptMap/$translate",
        )

    @patch("services.terminology_service.requests.post")
    def test_supports_codesystem_subsumes_operation(self, mock_post):
        response = Mock()
        response.raise_for_status.return_value = None
        mock_post.return_value = response

        call_terminology_operation(
            "CodeSystem",
            "$subsumes",
            {"resourceType": "Parameters"},
            base_url="https://tx.fhir.ch/r4",
        )

        self.assertEqual(
            mock_post.call_args.args[0],
            "https://tx.fhir.ch/r4/CodeSystem/$subsumes",
        )

    @patch("services.terminology_service.requests.post")
    def test_maps_cvx_to_snomed_before_validation(self, mock_post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"resourceType": "Parameters"}
        mock_post.return_value = response

        result = validate_coding(
            {
                "system": "http://hl7.org/fhir/sid/cvx",
                "code": "207",
            },
            base_url="https://tx.fhir.ch/r4",
        )

        self.assertEqual(result["status"], "validated")
        self.assertEqual(result["mapped_coding"]["code"], "1119349007")
        self.assertEqual(
            mock_post.call_args.args[0],
            "https://tx.fhir.ch/r4/CodeSystem/$lookup",
        )

    def test_skips_cvx_without_internal_snomed_mapping(self):
        result = validate_coding(
            {
                "system": "http://hl7.org/fhir/sid/cvx",
                "code": "184",
            }
        )

        self.assertEqual(result["status"], "skipped")

    @patch("services.terminology_service.requests.post")
    def test_calls_r4_validate_code_operation(self, mock_post):
        response = Mock()
        response.raise_for_status.return_value = None
        mock_post.return_value = response
        parameters = {
            "resourceType": "Parameters",
            "parameter": [{"name": "url", "valueUri": "http://loinc.org"}],
        }

        result = call_terminology_operation(
            "ValueSet",
            "$validate-code",
            parameters,
            base_url="https://tx.fhir.ch/r4/",
            timeout=12,
        )

        self.assertIs(result, response)
        mock_post.assert_called_once_with(
            "https://tx.fhir.ch/r4/ValueSet/$validate-code",
            json=parameters,
            headers={
                "Accept": "application/fhir+json",
                "Content-Type": "application/fhir+json",
            },
            timeout=12,
        )

    @patch("services.terminology_service.requests.post")
    def test_validates_loinc_directly(self, mock_post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"resourceType": "Parameters"}
        mock_post.return_value = response

        result = validate_coding(
            {"system": "http://loinc.org", "code": "8480-6"},
            base_url="https://tx.fhir.ch/r4",
        )

        self.assertEqual(result["status"], "validated")
        self.assertEqual(mock_post.call_args.args[0], "https://tx.fhir.ch/r4/CodeSystem/$lookup")


if __name__ == "__main__":
    unittest.main()
