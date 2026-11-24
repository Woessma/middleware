import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

from terminology import emediplan_medication_map as medication_map


def _write_workbook(path, headers, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    workbook.close()


def _write_version(archive_dir, version, pharmacode_rows, product_rows):
    version_dir = Path(archive_dir, version)
    version_dir.mkdir(parents=True)
    _write_workbook(
        version_dir
        / f"{version}__MappingPharmacodeToGtinToSwissmedicDescription.xlsx",
        [
            "Pharmacode",
            "GTIN",
            "Swissmedic-Nr + Packungscode",
            "Swissmedic Bezeichnung des Arzneimittels",
        ],
        pharmacode_rows,
    )
    _write_workbook(
        version_dir / f"{version}__MappingProductNumberToSwissmedicDescription.xlsx",
        ["PrdNr", "Swissmedic Bezeichnung des Arzneimittels"],
        product_rows,
    )
    (version_dir / "manifest.json").write_text(
        json.dumps({"version": version}), encoding="utf-8"
    )


class EmediplanMedicationMapArchiveTests(unittest.TestCase):
    def tearDown(self):
        medication_map.invalidate_medication_mapping_cache()

    def test_current_entries_override_archive_and_missing_ids_fall_back(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_dir = Path(temp_dir, "archive")
            archive_dir.mkdir()
            _write_version(
                archive_dir,
                "20261101",
                [
                    ["0001", "07600000000001", "P-1", "Old medicine"],
                    ["0003", "07600000000003", "P-3", "Archived medicine"],
                ],
                [["P-1", "Old medicine"], ["P-3", "Archived medicine"]],
            )
            _write_version(
                archive_dir,
                "20261201",
                [["0001", "07600000000002", "P-1", "Current medicine"]],
                [["P-1", "Current medicine"]],
            )
            Path(temp_dir, "current.json").write_text(
                json.dumps({"version": "20261201"}), encoding="utf-8"
            )

            with (
                patch.dict(os.environ, {"EMEDIPLAN_MAPPING_DATA_DIR": temp_dir}),
                patch.object(
                    medication_map, "DEFAULT_PHARMACODE_XLSX", "/missing/pharmacode.xlsx"
                ),
                patch.object(
                    medication_map,
                    "DEFAULT_PRODUCTNUMBER_XLSX",
                    "/missing/productnumber.xlsx",
                ),
            ):
                medication_map.invalidate_medication_mapping_cache()
                sources = medication_map._mapping_source_pairs()
                current = medication_map.resolve_medication_identity(3, "0001")
                archived = medication_map.resolve_medication_identity(3, "0003")
                old_product = medication_map.resolve_medication_identity(4, "P-3")

        self.assertEqual(len(sources), 2)
        self.assertTrue(
            all(Path(temp_dir, "archive") in Path(source[0]).parents for source in sources)
        )
        self.assertEqual(current["display"], "Current medicine")
        self.assertEqual(current["gtin"], "07600000000002")
        self.assertEqual(archived["display"], "Archived medicine")
        self.assertEqual(old_product["display"], "Archived medicine")

    def test_requires_persistent_archive_instead_of_using_bundled_workbooks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.dict(os.environ, {"EMEDIPLAN_MAPPING_DATA_DIR": temp_dir}),
                patch.object(medication_map, "DEFAULT_PHARMACODE_XLSX", "/bundled/pharmacode.xlsx"),
                patch.object(
                    medication_map,
                    "DEFAULT_PRODUCTNUMBER_XLSX",
                    "/bundled/productnumber.xlsx",
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "Kein persistentes eMediplan-Mapping-Archiv"
                ):
                    medication_map._mapping_source_pairs()


if __name__ == "__main__":
    unittest.main()
