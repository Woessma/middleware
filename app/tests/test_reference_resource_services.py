import unittest
from unittest.mock import Mock, patch

from services.organization_service import create_organization
from services.patient_service import create_patient
from services.practitioner_service import create_practitioner


class ReferenceResourceServiceTests(unittest.TestCase):
    @patch("services.patient_service.requests.post")
    def test_create_patient_uses_post_without_client_id(self, mock_post):
        response = Mock()
        response.content = b'{"id":"pat-1"}'
        response.json.return_value = {"id": "pat-1"}
        response.raise_for_status.return_value = None
        mock_post.return_value = response

        result = create_patient(
            {
                "resourceType": "Patient",
                "id": "temp-id",
                "identifier": [
                    {"system": "urn:oid:1.2.3", "value": "abc"}
                ],
            }
        )

        self.assertEqual(result["id"], "pat-1")
        mock_post.assert_called_once()
        self.assertNotIn("id", mock_post.call_args.kwargs["json"])

    @patch("services.practitioner_service.requests.put")
    def test_create_practitioner_uses_deterministic_put(self, mock_put):
        response = Mock()
        response.content = b'{"id":"prac-1"}'
        response.json.return_value = {"id": "prac-1"}
        response.raise_for_status.return_value = None
        mock_put.return_value = response

        result = create_practitioner(
            {
                "resourceType": "Practitioner",
                "id": "temp-id",
                "identifier": [
                    {"system": "urn:oid:9.8.7", "value": "17395"}
                ],
            }
        )

        self.assertEqual(result["id"], "prac-1")
        mock_put.assert_called_once()
        self.assertIn("/Practitioner/", mock_put.call_args.args[0])
        self.assertEqual(
            mock_put.call_args.kwargs["json"]["id"],
            mock_put.call_args.args[0].rsplit("/", 1)[-1],
        )

    @patch("services.organization_service.requests.put")
    def test_create_organization_uses_deterministic_put(self, mock_put):
        response = Mock()
        response.content = b'{"id":"org-1"}'
        response.json.return_value = {"id": "org-1"}
        response.raise_for_status.return_value = None
        mock_put.return_value = response

        result = create_organization(
            identifier_system="urn:oid:1.2.40.0.34.99.4613",
            identifier_value="1.2.40.0.34.99.4613",
            name="Amadeus Spital",
        )

        self.assertEqual(result["id"], "org-1")
        mock_put.assert_called_once()
        self.assertIn("/Organization/", mock_put.call_args.args[0])
        self.assertEqual(
            mock_put.call_args.kwargs["json"]["id"],
            mock_put.call_args.args[0].rsplit("/", 1)[-1],
        )

    @patch("services.organization_service.requests.get")
    def test_find_organization_prefers_lowest_active_match_when_duplicates_exist(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "total": 2,
            "entry": [
                {"resource": {"id": "3325", "active": True}},
                {"resource": {"id": "3322", "active": True}},
            ],
        }
        mock_get.return_value = response

        from services.organization_service import find_organization

        result = find_organization(
            "urn:oid:1.2.840.114350.1.13.521.2.7.2.688879",
            "48900",
        )

        self.assertEqual(result["id"], "3322")

    @patch("services.patient_service.requests.put")
    def test_update_patient_uses_put_by_id(self, mock_put):
        response = Mock()
        response.json.return_value = {"id": "pat-1"}
        response.raise_for_status.return_value = None
        mock_put.return_value = response

        from services.patient_service import update_patient

        result = update_patient(
            "pat-1",
            {
                "resourceType": "Patient",
                "identifier": [{"system": "urn:oid:1.2.3", "value": "abc"}],
            },
        )

        self.assertEqual(result["id"], "pat-1")
        self.assertEqual(mock_put.call_args.args[0], "http://fhir-server:8080/fhir/Patient/pat-1")
        self.assertEqual(mock_put.call_args.kwargs["json"]["id"], "pat-1")

    @patch("services.practitioner_service.requests.put")
    def test_update_practitioner_uses_put_by_id(self, mock_put):
        response = Mock()
        response.json.return_value = {"id": "prac-1"}
        response.raise_for_status.return_value = None
        mock_put.return_value = response

        from services.practitioner_service import update_practitioner

        result = update_practitioner(
            "prac-1",
            {
                "resourceType": "Practitioner",
                "identifier": [{"system": "urn:oid:9.8.7", "value": "17395"}],
            },
        )

        self.assertEqual(result["id"], "prac-1")
        self.assertEqual(mock_put.call_args.args[0], "http://fhir-server:8080/fhir/Practitioner/prac-1")
        self.assertEqual(mock_put.call_args.kwargs["json"]["id"], "prac-1")

    @patch("services.practitioner_service.requests.get")
    def test_find_practitioner_prefers_lowest_active_match_when_duplicates_exist(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "entry": [
                {"resource": {"id": "3324", "active": True}},
                {"resource": {"id": "3321", "active": True}},
            ]
        }
        mock_get.return_value = response

        from services.practitioner_service import find_practitioner

        result = find_practitioner(
            "https://woess.ch/fhir/NamingSystem/cda-import-practitioner",
            "d7fc4fa562885376abbc12d2873f9dfb9333cc78103c75bb121b68505554d413",
        )

        self.assertEqual(result["id"], "3321")