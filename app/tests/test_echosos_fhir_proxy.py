import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from main import FHIR_BASE, app


class EchoSosFhirProxyTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer test-token"}

    @patch("main.requests.post")
    def test_proxies_echo_import_body_and_authentication(self, mock_post):
        upstream = Mock()
        upstream.status_code = 200
        upstream.content = b'{"resourceType":"Bundle","type":"transaction-response"}'
        upstream.headers = {"Content-Type": "application/json;charset=utf-8"}
        mock_post.return_value = upstream
        body = b"----boundary\r\npayload\r\n----boundary--\r\n"
        content_type = "multipart/form-data; boundary=boundary"

        response = self.client.post(
            "/echosos/import",
            content=body,
            headers={
                **self.headers,
                "Content-Type": content_type,
                "Accept": "application/json",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, upstream.content)
        self.assertEqual(
            response.headers["content-type"],
            "application/json;charset=utf-8",
        )
        mock_post.assert_called_once_with(
            "https://api.omnilink.ch/v1/echosos/resolve",
            data=body,
            headers={
                "Authorization": "Bearer test-token",
                "Accept": "application/json",
                "Content-Type": content_type,
            },
            timeout=300,
        )

    @patch("main.requests.post")
    def test_rejects_echo_import_without_bearer_token(self, mock_post):
        response = self.client.post("/echosos/import", content=b"payload")

        self.assertEqual(response.status_code, 401)
        mock_post.assert_not_called()

    @patch("main.requests.get")
    def test_proxies_patient_everything_query_with_auth_and_query_parameters(
        self,
        mock_get,
    ):
        upstream = Mock()
        upstream.status_code = 200
        upstream.content = b'{"resourceType":"Bundle","entry":[]}'
        upstream.headers = {"Content-Type": "application/fhir+json"}
        mock_get.return_value = upstream

        response = self.client.get(
            "/echosos/fhir/Patient/123/$everything?_count=500",
            headers={
                **self.headers,
                "Accept": "application/fhir+json, application/json",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, upstream.content)
        self.assertEqual(response.headers["content-type"], "application/fhir+json")
        mock_get.assert_called_once_with(
            f"{FHIR_BASE.rstrip('/')}/Patient/123/$everything",
            params=[("_count", "500")],
            headers={
                "Accept": "application/fhir+json, application/json",
                "Authorization": "Bearer test-token",
            },
            timeout=30,
        )

    @patch("main.requests.get")
    def test_rejects_requests_without_bearer_token(self, mock_get):
        response = self.client.get("/echosos/fhir/Patient/123/$everything")

        self.assertEqual(response.status_code, 401)
        mock_get.assert_not_called()

    @patch("main.requests.get")
    def test_rejects_non_patient_fhir_paths(self, mock_get):
        response = self.client.get(
            "/echosos/fhir/Observation/123",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 404)
        mock_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
