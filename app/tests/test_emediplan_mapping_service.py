import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from openpyxl import Workbook

from services.emediplan_mapping_service import (
    EmediplanMappingRefreshError,
    _download_workbook,
    discover_mapping_urls,
    refresh_emediplan_mappings,
)


def _workbook_bytes(headers, row):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def _page(version="20261201"):
    return f"""
    <a href="/s/{version}__MappingProductNumberToSwissmedicDescription.xlsx">Product</a>
    <a href="/s/{version}__MappingPharmacodeToGtinToSwissmedicDescription.xlsx">Pharmacode</a>
    <a href="https://github.com/ig-emediplan/specification">Other link</a>
    """


class EmediplanMappingDiscoveryTests(unittest.TestCase):
    def test_discovers_matching_version_and_ignores_unrelated_links(self):
        version, urls = discover_mapping_urls(_page())

        self.assertEqual(version, "20261201")
        self.assertEqual(
            urls["pharmacode"],
            "https://www.emediplan.ch/s/20261201__MappingPharmacodeToGtinToSwissmedicDescription.xlsx",
        )

    def test_rejects_incomplete_publication_pair(self):
        html = """
        <a href="/s/20261201__MappingProductNumberToSwissmedicDescription.xlsx">Product</a>
        <a href="/s/20261101__MappingPharmacodeToGtinToSwissmedicDescription.xlsx">Pharmacode</a>
        """

        with self.assertRaises(EmediplanMappingRefreshError):
            discover_mapping_urls(html)

    def test_rejects_mapping_link_to_untrusted_host(self):
        html = """
        <a href="https://attacker.example/20261201__MappingProductNumberToSwissmedicDescription.xlsx">Product</a>
        <a href="/s/20261201__MappingPharmacodeToGtinToSwissmedicDescription.xlsx">Pharmacode</a>
        """

        with self.assertRaises(EmediplanMappingRefreshError):
            discover_mapping_urls(html)

    @patch("services.emediplan_mapping_service.requests.get")
    def test_accepts_redirect_to_expected_squarespace_cdn_file(self, get):
        response = MagicMock()
        response.url = (
            "https://static1.squarespace.com/files/"
            "20261201__MappingProductNumberToSwissmedicDescription.xlsx"
        )
        response.headers = {}
        response.iter_content.return_value = [b"xlsx-content"]
        response_context = MagicMock()
        response_context.__enter__.return_value = response
        get.return_value = response_context

        result = _download_workbook(
            "https://www.emediplan.ch/s/"
            "20261201__MappingProductNumberToSwissmedicDescription.xlsx",
            timeout=10,
        )

        self.assertEqual(result, b"xlsx-content")


class EmediplanMappingRefreshTests(unittest.TestCase):
    def test_archives_pair_activates_version_and_is_idempotent(self):
        files = {
            "pharmacode": _workbook_bytes(
                ["Pharmacode", "GTIN"], ["111", "07600000000001"]
            ),
            "product_number": _workbook_bytes(
                ["PrdNr", "Swissmedic Bezeichnung des Arzneimittels"],
                ["P-1", "Example medicine"],
            ),
        }

        def download(url, _timeout):
            return files["product_number" if "ProductNumber" in url else "pharmacode"]

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "services.emediplan_mapping_service._get_index_html",
            return_value=_page(),
        ), patch(
            "services.emediplan_mapping_service._download_workbook",
            side_effect=download,
        ), patch(
            "services.emediplan_mapping_service.invalidate_medication_mapping_cache"
        ) as invalidate:
            first = refresh_emediplan_mappings(data_dir=temp_dir)
            second = refresh_emediplan_mappings(data_dir=temp_dir)

            archive = Path(temp_dir, "archive", "20261201")
            self.assertTrue(
                (archive / "20261201__MappingPharmacodeToGtinToSwissmedicDescription.xlsx").is_file()
            )
            baseline = Path(temp_dir, "archive", "bundled")
            self.assertTrue(
                (baseline / "MappingPharmacodeToGtinToSwissmedicDescription.xlsx").is_file()
            )
            archive_manifest = json.loads(
                (archive / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertIn("url", archive_manifest["files"]["pharmacode"])
            current = json.loads(
                Path(temp_dir, "current.json").read_text(encoding="utf-8")
            )
            self.assertEqual(current["version"], "20261201")
            self.assertTrue(first["updated"])
            self.assertFalse(second["updated"])
            invalidate.assert_called_once()

    def test_invalid_workbook_does_not_change_active_version(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "services.emediplan_mapping_service._get_index_html",
            return_value=_page(),
        ), patch(
            "services.emediplan_mapping_service._download_workbook",
            return_value=b"not an xlsx",
        ):
            with self.assertRaises(EmediplanMappingRefreshError):
                refresh_emediplan_mappings(data_dir=temp_dir)

            self.assertFalse(Path(temp_dir, "current.json").exists())
            self.assertFalse(Path(temp_dir, "archive", "20261201").exists())

    def test_does_not_downgrade_active_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "archive", "20261201").mkdir(parents=True)
            Path(temp_dir, "current.json").write_text(
                json.dumps({"version": "20261201"}), encoding="utf-8"
            )
            with patch(
                "services.emediplan_mapping_service._get_index_html",
                return_value=_page("20261101"),
            ), patch(
                "services.emediplan_mapping_service._download_workbook"
            ) as download:
                with self.assertRaises(EmediplanMappingRefreshError):
                    refresh_emediplan_mappings(data_dir=temp_dir)
                download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
