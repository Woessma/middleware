import unittest
from unittest.mock import Mock, patch

from services.refdata_service import lookup_gln

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
    def test_returns_none_when_api_key_missing(self):
        result = lookup_gln("7601009545993", api_key="")
        self.assertIsNone(result)

    @patch("services.refdata_service.requests.post")
    def test_finds_and_parses_matching_item(self, mock_post):
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

    @patch("services.refdata_service.requests.post")
    def test_returns_none_when_gln_not_in_response(self, mock_post):
        response = Mock()
        response.content = _SAMPLE_RESPONSE.encode("utf-8")
        response.raise_for_status = Mock()
        mock_post.return_value = response

        result = lookup_gln("0000000000000", api_key="dummy-key")

        self.assertIsNone(result)

    @patch("services.refdata_service.requests.post")
    def test_returns_none_on_request_error(self, mock_post):
        mock_post.side_effect = Exception("network error")

        result = lookup_gln("7601009545993", api_key="dummy-key")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
