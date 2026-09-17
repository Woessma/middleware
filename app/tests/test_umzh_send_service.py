import unittest
from unittest.mock import Mock, patch

from services.umzh_send_service import send_umzh_bundle


class UmzhSendServiceTests(unittest.TestCase):
    def _response(self, status_code=200, payload=None):
        response = Mock()
        response.status_code = status_code
        response.json.return_value = payload if payload is not None else {"ok": True}
        response.text = "text"
        return response

    def test_send_umzh_bundle_success(self):
        bundle = {
            "entry": [
                {
                    "resource": {
                        "resourceType": "ServiceRequest",
                        "id": "sr-1",
                    }
                },
                {
                    "resource": {
                        "resourceType": "Task",
                        "id": "task-1",
                    }
                },
            ]
        }

        with patch("services.umzh_send_service.requests.put") as put_mock:
            put_mock.side_effect = [
                self._response(201, {"resourceType": "ServiceRequest"}),
                self._response(200, {"resourceType": "Task"}),
            ]

            report = send_umzh_bundle(
                bundle=bundle,
                destination_base_url="http://example.org/fhir",
                timeout_seconds=30,
            )

        self.assertEqual(report["status"], "sent")
        self.assertEqual(report["sent_ok_count"], 2)
        self.assertEqual(report["failed_count"], 0)

    def test_send_umzh_bundle_partial_error(self):
        bundle = {
            "entry": [
                {
                    "resource": {
                        "resourceType": "ServiceRequest",
                        "id": "sr-1",
                    }
                },
                {
                    "resource": {
                        "resourceType": "Task",
                        "id": "task-1",
                    }
                },
            ]
        }

        with patch("services.umzh_send_service.requests.put") as put_mock:
            put_mock.side_effect = [
                self._response(201, {"resourceType": "ServiceRequest"}),
                Exception("network failure"),
            ]

            report = send_umzh_bundle(
                bundle=bundle,
                destination_base_url="http://example.org/fhir",
                timeout_seconds=30,
            )

        self.assertEqual(report["status"], "partial-error")
        self.assertEqual(report["sent_ok_count"], 1)
        self.assertEqual(report["failed_count"], 1)


if __name__ == "__main__":
    unittest.main()
