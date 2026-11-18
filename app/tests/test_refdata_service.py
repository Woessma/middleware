import io
import unittest
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from services.refdata_service import (
    RefdataRefreshError,
    enrich_organization_resource,
    enrich_practitioner_resource,
    lookup_gln,
    refresh_partner_files,
)

_SAMPLE_RESPONSE = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <PARTNER xmlns="http://refdatabase.refdata.ch/V2/Partner_out" CREATION_DATETIME="2026-08-27T00:00:00">
      <ITEM DT="2026-08-27T00:00:00">
        <PTYPE>JUR</PTYPE>
        <GLN>7601009545993</GLN>
        <STATUS>A</STATUS>
        <STDATE>2026-03-03T15:29:59.263</STDATE>
        <LANG>DE</LANG>
        <DESCR1>EuroVitality Trading AG</DESCR1>
        <DESCR2></DESCR2>
        <ROLE>
          <TYPE>Indus</TYPE>
          <STREET>Seestrasse</STREET>
          <STRNO>15</STRNO>
          <ZIP>6300</ZIP>
          <CITY>Zug</CITY>
          <CTN>ZG</CTN>
          <CNTRY>CH</CNTRY>
        </ROLE>
      </ITEM>
      <ITEM DT="2026-08-27T00:00:00">
        <PTYPE>JUR</PTYPE>
        <GLN>7601009999999</GLN>
        <STATUS>A</STATUS>
        <STDATE>2026-03-03T15:29:59.263</STDATE>
        <DESCR1>Some Other Company</DESCR1>
      </ITEM>
    </PARTNER>
  </soap:Body>
</soap:Envelope>"""


class RefdataServiceTests(unittest.TestCase):
    @patch("services.refdata_service._lookup_gln_xml", return_value=None)
    def test_returns_none_when_api_key_missing(self, _mock_local_lookup):
        result = lookup_gln("7601009545993", api_key="")
        self.assertIsNone(result)

    @patch("services.refdata_service._lookup_gln_xml", return_value=None)
    @patch("services.refdata_service.requests.post")
    def test_finds_and_parses_matching_item(self, mock_post, _mock_local_lookup):
        response = Mock()
        response.content = _SAMPLE_RESPONSE.encode("utf-8")
        response.raise_for_status = Mock()
        mock_post.return_value = response

        result = lookup_gln("7601009545993", api_key="dummy-key")

        self.assertEqual(result["gln"], "7601009545993")
        self.assertEqual(result["name"], "EuroVitality Trading AG")
        self.assertEqual(result["status"], "A")
        self.assertEqual(result["address"]["line"], ["Seestrasse 15"])
        self.assertEqual(result["address"]["postalCode"], "6300")
        self.assertEqual(result["address"]["city"], "Zug")
        self.assertEqual(result["address"]["state"], "ZG")
        self.assertEqual(result["address"]["country"], "CH")

    @patch("services.refdata_service._lookup_gln_xml", return_value=None)
    @patch("services.refdata_service.requests.post")
    def test_returns_none_when_gln_not_in_response(self, mock_post, _mock_local_lookup):
        response = Mock()
        response.content = _SAMPLE_RESPONSE.encode("utf-8")
        response.raise_for_status = Mock()
        mock_post.return_value = response

        result = lookup_gln("0000000000000", api_key="dummy-key")

        self.assertIsNone(result)

    @patch("services.refdata_service._lookup_gln_xml", return_value=None)
    @patch("services.refdata_service.requests.post")
    def test_returns_none_on_request_error(self, mock_post, _mock_local_lookup):
        mock_post.side_effect = Exception("network error")

        result = lookup_gln("7601009545993", api_key="dummy-key")

        self.assertIsNone(result)

    def test_looks_up_nat_and_jur_records_from_local_xml(self):
        nat_xml = """<PARTNER xmlns="http://refdatabase.refdata.ch/">
          <ITEM xmlns="http://refdatabase.refdata.ch/Partner_out" DT="2026-11-03">
            <PTYPE>NAT</PTYPE><GLN>7601000115690</GLN><STATUS>A</STATUS>
            <DESCR1>Burgener</DESCR1><DESCR2>Roland</DESCR2>
            <ROLE><STREET>Hauptstrasse</STREET><STRNO>4</STRNO><ZIP>3000</ZIP>
              <CITY>Bern</CITY><CTN>BE</CTN><CNTRY>CH</CNTRY></ROLE>
          </ITEM>
        </PARTNER>"""
        jur_xml = """<PARTNER xmlns="http://refdatabase.refdata.ch/">
          <ITEM xmlns="http://refdatabase.refdata.ch/Partner_out" DT="2026-11-03">
            <PTYPE>JUR</PTYPE><GLN>7601001028333</GLN><STATUS>A</STATUS>
            <DESCR1>St Martini Apotheke</DESCR1><DESCR2>GaleniCare AG</DESCR2>
            <ROLE><STREET>Marktgasse</STREET><STRNO>2</STRNO><ZIP>6000</ZIP>
              <CITY>Luzern</CITY><CTN>LU</CTN><CNTRY>CH</CNTRY></ROLE>
          </ITEM>
        </PARTNER>"""

        with tempfile.TemporaryDirectory() as temp_dir:
            nat_path = Path(temp_dir, "nat.xml")
            jur_path = Path(temp_dir, "jur.xml")
            nat_path.write_text(nat_xml, encoding="utf-8")
            jur_path.write_text(jur_xml, encoding="utf-8")
            with (
                patch.dict(
                    "services.refdata_service._REFDATA_XML_FILES",
                    {"NAT": nat_path, "JUR": jur_path},
                ),
                patch("services.refdata_service.tempfile.gettempdir", return_value=temp_dir),
            ):
                natural_person = lookup_gln(
                    "7601000115690", api_key="", partner_type="NAT"
                )
                legal_person = lookup_gln(
                    "7601001028333", api_key="", partner_type="JUR"
                )

        self.assertEqual(natural_person["given_name"], "Roland")
        self.assertEqual(natural_person["family_name"], "Burgener")
        self.assertEqual(natural_person["address"]["line"], ["Hauptstrasse 4"])
        self.assertEqual(natural_person["address"]["state"], "BE")
        self.assertEqual(legal_person["name"], "St Martini Apotheke")
        self.assertEqual(legal_person["name2"], "GaleniCare AG")
        self.assertEqual(legal_person["address"]["city"], "Luzern")

    @patch(
        "services.refdata_service.lookup_gln",
        return_value={
            "given_name": "Roland",
            "family_name": "Burgener",
            "address": {"line": ["Hauptstrasse 4"], "city": "Bern"},
        },
    )
    def test_enriches_practitioner_without_overwriting_source_fields(self, mock_lookup):
        original = {
            "resourceType": "Practitioner",
            "identifier": [{"system": "urn:oid:2.51.1.3", "value": "7601000115690"}],
            "name": [{"family": "Source"}],
        }

        result = enrich_practitioner_resource(original)

        self.assertEqual(result["name"], [{"family": "Source", "given": ["Roland"]}])
        self.assertEqual(result["address"][0]["city"], "Bern")
        self.assertNotIn("address", original)
        mock_lookup.assert_called_once_with("7601000115690", partner_type="NAT")

    @patch(
        "services.refdata_service.lookup_gln",
        return_value={
            "name": "Praxis am See",
            "given_name": None,
            "family_name": None,
        },
    )
    def test_practitioner_without_family_name_gets_no_name(self, mock_lookup):
        # ch-pract-1: a HumanName without family would violate CH-Core.
        result = enrich_practitioner_resource(
            {
                "resourceType": "Practitioner",
                "identifier": [{"system": "urn:oid:2.51.1.3", "value": "7601000115690"}],
            }
        )

        self.assertNotIn("name", result)

    @patch(
        "services.refdata_service.lookup_gln",
        return_value={
            "name": "St Martini Apotheke",
            "name2": "GaleniCare AG",
            "address": {"line": ["Marktgasse 2"], "city": "Luzern"},
        },
    )
    def test_enriches_organization_name_alias_and_address(self, mock_lookup):
        result = enrich_organization_resource(
            {
                "resourceType": "Organization",
                "identifier": [
                    {"system": "urn:oid:2.51.1.3", "value": "7601001028333"}
                ],
            }
        )

        self.assertEqual(result["name"], "St Martini Apotheke")
        self.assertEqual(result["alias"], ["GaleniCare AG"])
        self.assertEqual(result["address"][0]["city"], "Luzern")
        mock_lookup.assert_called_once_with("7601001028333", partner_type="JUR")


_NAT_EXPORT_XML = """<PARTNER xmlns="http://refdatabase.refdata.ch/">
  <ITEM xmlns="http://refdatabase.refdata.ch/Partner_out" DT="2026-11-18">
    <PTYPE>NAT</PTYPE><GLN>7601000115690</GLN><STATUS>A</STATUS>
    <DESCR1>Burgener</DESCR1><DESCR2>Roland</DESCR2>
  </ITEM>
</PARTNER>"""

_JUR_EXPORT_XML = """<PARTNER xmlns="http://refdatabase.refdata.ch/">
  <ITEM xmlns="http://refdatabase.refdata.ch/Partner_out" DT="2026-11-18">
    <PTYPE>JUR</PTYPE><GLN>7601001028333</GLN><STATUS>A</STATUS>
    <DESCR1>St Martini Apotheke</DESCR1>
  </ITEM>
</PARTNER>"""


def _export_zip_bytes(nat_xml=_NAT_EXPORT_XML, jur_xml=_JUR_EXPORT_XML):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Refdata.Partners.Nat.xml", nat_xml)
        archive.writestr("Refdata.Partners.Jur.xml", jur_xml)
    return buffer.getvalue()


def _mock_zip_response(zip_bytes):
    response = MagicMock()
    response.raise_for_status = Mock()
    response.iter_content.return_value = [zip_bytes]
    context = MagicMock()
    context.__enter__.return_value = response
    return context


class RefdataRefreshTests(unittest.TestCase):
    def test_refresh_requires_api_key(self):
        with self.assertRaises(RefdataRefreshError):
            refresh_partner_files(api_key="")

    @patch("services.refdata_service.requests.get")
    def test_refresh_downloads_replaces_and_detects_unchanged(self, mock_get):
        mock_get.return_value = _mock_zip_response(_export_zip_bytes())

        with tempfile.TemporaryDirectory() as temp_dir:
            results = refresh_partner_files(
                api_key="dummy-key", url="https://example.test/zip", data_dir=temp_dir
            )

            nat_path = Path(temp_dir, "Refdata.Partners.Nat.xml")
            jur_path = Path(temp_dir, "Refdata.Partners.Jur.xml")
            self.assertTrue(nat_path.is_file())
            self.assertTrue(jur_path.is_file())
            self.assertTrue(results["NAT"]["updated"])
            self.assertTrue(results["JUR"]["updated"])
            self.assertEqual(results["NAT"]["items"], 1)

            headers = mock_get.call_args.kwargs["headers"]
            self.assertEqual(headers["X-API-Key"], "dummy-key")

            # Same export again: files stay in place, nothing is marked updated.
            mock_get.return_value = _mock_zip_response(_export_zip_bytes())
            second = refresh_partner_files(
                api_key="dummy-key", url="https://example.test/zip", data_dir=temp_dir
            )
            self.assertFalse(second["NAT"]["updated"])
            self.assertFalse(second["JUR"]["updated"])

            # The refreshed directory takes precedence over the bundled files.
            with (
                patch("services.refdata_service.REFDATA_DATA_DIR", temp_dir),
                patch("services.refdata_service.tempfile.gettempdir", return_value=temp_dir),
            ):
                entry = lookup_gln("7601000115690", api_key="", partner_type="NAT")
            self.assertEqual(entry["family_name"], "Burgener")

    @patch("services.refdata_service.requests.get")
    def test_refresh_rejects_zip_without_expected_files(self, mock_get):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("Refdata.Partners.Nat.xml", _NAT_EXPORT_XML)
        mock_get.return_value = _mock_zip_response(buffer.getvalue())

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(RefdataRefreshError):
                refresh_partner_files(
                    api_key="dummy-key", url="https://example.test/zip", data_dir=temp_dir
                )
            self.assertFalse(Path(temp_dir, "Refdata.Partners.Nat.xml").exists())

    @patch("services.refdata_service.requests.get")
    def test_refresh_rejects_export_with_wrong_partner_type(self, mock_get):
        mock_get.return_value = _mock_zip_response(
            _export_zip_bytes(nat_xml=_JUR_EXPORT_XML)
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(RefdataRefreshError):
                refresh_partner_files(
                    api_key="dummy-key", url="https://example.test/zip", data_dir=temp_dir
                )
            self.assertFalse(Path(temp_dir, "Refdata.Partners.Jur.xml").exists())


if __name__ == "__main__":
    unittest.main()
