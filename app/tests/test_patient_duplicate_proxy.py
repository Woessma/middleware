import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from config import FHIR_EXTERNAL_TIMEOUT
from main import app


class ExternalPatientDuplicateProxyTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        patcher = patch("main.FHIR_EXTERNAL_BASE_URL", "https://fhir.woess.ch/fhir")
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch("main.FHIR_BASE", "http://fhir-server:8080/fhir")
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("main.requests.get")
    def test_forwards_search_and_external_auth_to_fixed_server(self, mock_get):
        upstream = Mock()
        upstream.status_code = 200
        upstream.content = b'{"resourceType":"Bundle","total":1,"entry":[]}'
        upstream.headers = {"Content-Type": "application/fhir+json"}
        mock_get.return_value = upstream

        response = self.client.post(
            "/fhir/patient-duplicate-test/external-search",
            json={
                "family": "Beispiel",
                "given": "Eva",
                "birthdate": "1990-01-15",
                "_count": "20",
            },
            headers={
                "Authorization": "Bearer local-keycloak-token",
                "X-FHIR-External-Authorization": "Basic external-credentials",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, upstream.content)
        mock_get.assert_called_once_with(
            "https://fhir.woess.ch/fhir/Patient",
            params={
                "family": "Beispiel",
                "given": "Eva",
                "birthdate": "1990-01-15",
                "_count": "20",
            },
            headers={
                "Accept": "application/fhir+json, application/json",
                "Authorization": "Basic external-credentials",
            },
            timeout=FHIR_EXTERNAL_TIMEOUT,
        )

    @patch("main.requests.get")
    def test_requires_keycloak_bearer_token(self, mock_get):
        response = self.client.post(
            "/fhir/patient-duplicate-test/external-search",
            json={"identifier": "urn:oid:1.2.3|123"},
        )

        self.assertEqual(response.status_code, 401)
        mock_get.assert_not_called()

    @patch("main.requests.get")
    def test_rejects_unsupported_query_parameters(self, mock_get):
        response = self.client.post(
            "/fhir/patient-duplicate-test/external-search",
            json={"identifier": "urn:oid:1.2.3|123", "url": "http://example.invalid"},
            headers={"Authorization": "Bearer local-keycloak-token"},
        )

        self.assertEqual(response.status_code, 400)
        mock_get.assert_not_called()

    @patch("main.requests.get")
    def test_rejects_ambiguous_search_and_excessive_count(self, mock_get):
        headers = {"Authorization": "Bearer local-keycloak-token"}
        ambiguous = self.client.post(
            "/fhir/patient-duplicate-test/external-search",
            json={
                "identifier": "urn:oid:1.2.3|123",
                "family": "Beispiel",
                "given": "Eva",
                "birthdate": "1990-01-15",
            },
            headers=headers,
        )
        excessive = self.client.post(
            "/fhir/patient-duplicate-test/external-search",
            json={"identifier": "urn:oid:1.2.3|123", "_count": "101"},
            headers=headers,
        )

        self.assertEqual(ambiguous.status_code, 400)
        self.assertEqual(excessive.status_code, 400)
        mock_get.assert_not_called()

    @patch("main.requests.get")
    def test_local_search_forwards_keycloak_token(self, mock_get):
        upstream = Mock()
        upstream.status_code = 200
        upstream.content = b'{"resourceType":"Bundle","total":0,"entry":[]}'
        upstream.headers = {"Content-Type": "application/fhir+json"}
        mock_get.return_value = upstream

        response = self.client.post(
            "/fhir/patient-duplicate-test/local-search",
            json={"identifier": "urn:oid:1.2.3|123"},
            headers={"Authorization": "Bearer keycloak-token"},
        )

        self.assertEqual(response.status_code, 200)
        mock_get.assert_called_once_with(
            "http://fhir-server:8080/fhir/Patient",
            params={"identifier": "urn:oid:1.2.3|123", "_count": "20"},
            headers={
                "Accept": "application/fhir+json, application/json",
                "Authorization": "Bearer keycloak-token",
            },
            timeout=30,
        )

    @patch("main.requests.get")
    def test_local_everything_fetches_patient_bundle_with_page_size_500(self, mock_get):
        upstream = Mock()
        upstream.status_code = 200
        upstream.content = b'{"resourceType":"Bundle","entry":[]}'
        upstream.headers = {"Content-Type": "application/fhir+json"}
        mock_get.return_value = upstream

        response = self.client.post(
            "/fhir/patient-duplicate-test/local-everything",
            json={"patientId": "123"},
            headers={"Authorization": "Bearer keycloak-token"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, upstream.content)
        mock_get.assert_called_once_with(
            "http://fhir-server:8080/fhir/Patient/123/$everything",
            params={"_count": "500"},
            headers={
                "Accept": "application/fhir+json, application/json",
                "Authorization": "Bearer keycloak-token",
            },
            timeout=30,
            allow_redirects=False,
        )

    @patch("main.requests.get")
    def test_everything_combines_pages_and_rejects_invalid_patient_ids(self, mock_get):
        next_url = "https://fhir.woess.ch/fhir?_getpages=next"
        mock_get.side_effect = [
            Mock(
                status_code=200,
                content=(
                    b'{"resourceType":"Bundle","entry":[{"resource":'
                    b'{"resourceType":"Patient","id":"123"}}],"link":'
                    b'[{"relation":"next","url":"' + next_url.encode() + b'"}]}'
                ),
                headers={"Content-Type": "application/fhir+json"},
            ),
            Mock(
                status_code=200,
                content=b'{"resourceType":"Bundle","entry":[{"resource":{"resourceType":"Observation","id":"obs-1"}}]}',
                headers={"Content-Type": "application/fhir+json"},
            ),
        ]

        response = self.client.post(
            "/fhir/patient-duplicate-test/external-everything",
            json={"patientId": "123"},
            headers={
                "Authorization": "Bearer keycloak-token",
                "X-FHIR-External-Authorization": "Basic external-credentials",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["entry"]), 2)
        self.assertEqual(response.json()["link"], [])
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(
            mock_get.call_args_list[0].args[0],
            "https://fhir.woess.ch/fhir/Patient/123/$everything",
        )
        self.assertEqual(mock_get.call_args_list[0].kwargs["params"], {"_count": "500"})
        self.assertEqual(
            mock_get.call_args_list[0].kwargs["headers"]["Authorization"],
            "Basic external-credentials",
        )
        self.assertEqual(mock_get.call_args_list[1].args[0], next_url)
        self.assertFalse(mock_get.call_args_list[1].kwargs["allow_redirects"])

        mock_get.reset_mock()
        invalid = self.client.post(
            "/fhir/patient-duplicate-test/external-everything",
            json={"patientId": "123/$everything"},
            headers={"Authorization": "Bearer keycloak-token"},
        )
        self.assertEqual(invalid.status_code, 400)
        mock_get.assert_not_called()

    @patch("main.requests.get")
    def test_external_everything_rejects_foreign_pagination_links(self, mock_get):
        mock_get.return_value = Mock(
            status_code=200,
            content=(
                b'{"resourceType":"Bundle","entry":[],"link":'
                b'[{"relation":"next","url":"https://attacker.invalid/collect"}]}'
            ),
            headers={"Content-Type": "application/fhir+json"},
        )

        response = self.client.post(
            "/fhir/patient-duplicate-test/external-everything",
            json={"patientId": "123"},
            headers={"Authorization": "Bearer keycloak-token"},
        )

        self.assertEqual(response.status_code, 502)
        self.assertIn("unvollständig", response.json()["detail"])
        self.assertEqual(mock_get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
