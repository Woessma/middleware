import unittest
import json
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
    def test_forwards_raw_camera_and_file_bodies_unchanged(self, mock_post):
        upstream = Mock()
        upstream.status_code = 200
        upstream.content = b'{"resourceType":"Bundle","type":"transaction-response"}'
        upstream.headers = {"Content-Type": "application/json"}
        mock_post.return_value = upstream

        for body, content_type in (
            (
                b"https://eid.echosos.com/#f=Test&l=Beispiel&g=fGBP",
                "text/plain; charset=utf-8",
            ),
            (b"\x89PNG\r\n\x1a\nsynthetic", "image/png"),
            (b"PKsynthetic", "application/vnd.apple.pkpass"),
        ):
            with self.subTest(content_type=content_type):
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
                self.assertEqual(mock_post.call_args.kwargs["data"], body)
                self.assertEqual(
                    mock_post.call_args.kwargs["headers"]["Content-Type"],
                    content_type,
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
    def test_everything_combines_all_pages_without_filtering_resource_types(self, mock_get):
        next_url = f"{FHIR_BASE.rstrip('/')}?_getpages=synthetic&_getpagesoffset=500"
        pages = [
            {
                "resourceType": "Bundle",
                "type": "searchset",
                "entry": [{"resource": {"resourceType": "Patient", "id": "123"}}] + [
                    {"resource": {"resourceType": "Observation", "id": str(index)}}
                    for index in range(499)
                ],
                "link": [{"relation": "next", "url": next_url}],
            },
            {
                "resourceType": "Bundle",
                "type": "searchset",
                "entry": [
                    {"resource": {"resourceType": resource_type, "id": str(index)}}
                    for index, resource_type in enumerate(
                        ["Encounter", "Composition", "CareTeam", "Observation"]
                    )
                ],
            },
        ]
        mock_get.side_effect = [
            Mock(status_code=200, content=json.dumps(page).encode())
            for page in pages
        ]

        response = self.client.get(
            "/echosos/fhir/Patient/123/$everything?_count=500", headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["entry"]), 504)
        self.assertEqual(response.json()["link"], [])
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_get.call_args.args, (next_url,))
        self.assertEqual(mock_get.call_args.kwargs["headers"]["Authorization"], self.headers["Authorization"])
        self.assertFalse(mock_get.call_args.kwargs["allow_redirects"])

    @patch("main.requests.get")
    def test_everything_rejects_unsafe_or_cyclic_pagination(self, mock_get):
        for next_url in (
            "https://example.org/fhir?_getpages=foreign",
            f"{FHIR_BASE.rstrip('/')}/Observation",
            f"{FHIR_BASE.rstrip('/')}?_getpages=cycle",
        ):
            with self.subTest(next_url=next_url):
                page = {
                    "resourceType": "Bundle", "entry": [],
                    "link": [{"relation": "next", "url": next_url}],
                }
                mock_get.reset_mock()
                mock_get.side_effect = None
                mock_get.return_value = Mock(status_code=200, content=json.dumps(page).encode())
                response = self.client.get(
                    "/echosos/fhir/Patient/123/$everything?_count=500", headers=self.headers,
                )
                self.assertEqual(response.status_code, 502)
                self.assertLessEqual(mock_get.call_count, 2)

    @patch("main.requests.get")
    def test_everything_does_not_report_partial_results_as_success(self, mock_get):
        first = {
            "resourceType": "Bundle", "entry": [],
            "link": [{"relation": "next", "url": f"{FHIR_BASE.rstrip('/')}?_getpages=test"}],
        }
        for next_page in (
            Mock(status_code=500, content=b"unavailable"),
            Mock(status_code=200, content=b'{"resourceType":"OperationOutcome"}'),
            Mock(status_code=200, content=b"not JSON"),
            Mock(status_code=302, content=b"redirect"),
            Mock(status_code=200, content=b'{"resourceType":"Bundle","link":["invalid"]}'),
            Mock(status_code=200, content=b'{"resourceType":"Bundle","entry":null}'),
        ):
            with self.subTest(next_page=next_page):
                mock_get.side_effect = [
                    Mock(status_code=200, content=json.dumps(first).encode()), next_page,
                ]
                response = self.client.get(
                    "/echosos/fhir/Patient/123/$everything?_count=500", headers=self.headers,
                )
                self.assertEqual(response.status_code, 502)
                self.assertIn("unvollständig", response.json()["detail"])

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
