import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from main import BRIDGELINK_CDA_URL, app


class BridgeLinkCdaProxyTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("main.requests.post")
    def test_forwards_raw_cda_and_bearer_token_to_fixed_bridge_endpoint(self, mock_post):
        upstream = Mock()
        upstream.status_code = 200
        upstream.content = b'{"resourceType":"Bundle"}'
        upstream.headers = {"Content-Type": "application/fhir+json"}
        mock_post.return_value = upstream

        response = self.client.post(
            "/_proxy/bridge/cda",
            content=b"<ClinicalDocument />",
            headers={
                "Authorization": "Bearer test-token",
                "Content-Type": "application/xml",
                "Accept": "application/fhir+json",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, upstream.content)
        mock_post.assert_called_once_with(
            BRIDGELINK_CDA_URL,
            data=b"<ClinicalDocument />",
            headers={
                "Authorization": "Bearer test-token",
                "Accept": "application/fhir+json",
                "Content-Type": "application/xml",
            },
            timeout=300,
        )

    @patch("main.requests.post")
    def test_rejects_requests_without_bearer_token(self, mock_post):
        response = self.client.post(
            "/_proxy/bridge/cda",
            content=b"<ClinicalDocument />",
            headers={"Content-Type": "application/xml"},
        )

        self.assertEqual(response.status_code, 401)
        mock_post.assert_not_called()

    @patch("main.requests.post")
    def test_forwards_multipart_body_and_boundary_unchanged(self, mock_post):
        upstream = Mock()
        upstream.status_code = 200
        upstream.content = b"ok"
        upstream.headers = {"Content-Type": "application/json"}
        mock_post.return_value = upstream
        boundary = "----test-boundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="sample.xml"\r\n'
            "Content-Type: application/xml\r\n\r\n"
            "<ClinicalDocument />\r\n"
            f"--{boundary}--\r\n"
        ).encode()
        content_type = f"multipart/form-data; boundary={boundary}"

        response = self.client.post(
            "/_proxy/bridge/cda",
            content=body,
            headers={
                "Authorization": "Bearer test-token",
                "Content-Type": content_type,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_post.call_args.kwargs["data"], body)
        self.assertEqual(
            mock_post.call_args.kwargs["headers"]["Content-Type"],
            content_type,
        )