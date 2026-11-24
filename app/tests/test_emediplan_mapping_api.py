import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from services.emediplan_mapping_service import EmediplanMappingRefreshError


class EmediplanMappingApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch(
        "main.refresh_emediplan_mappings",
        return_value={"version": "20261201", "updated": True, "files": {}},
    )
    def test_refresh_returns_archive_summary(self, refresh):
        response = self.client.post("/admin/api/emediplan-mappings/refresh")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], "20261201")
        self.assertTrue(response.json()["updated"])
        refresh.assert_called_once()

    @patch(
        "main.refresh_emediplan_mappings",
        side_effect=EmediplanMappingRefreshError("upstream unavailable", 503),
    )
    def test_refresh_surfaces_upstream_failure(self, _refresh):
        response = self.client.post("/admin/api/emediplan-mappings/refresh")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "upstream unavailable")


if __name__ == "__main__":
    unittest.main()
