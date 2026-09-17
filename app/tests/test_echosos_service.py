import io
import json
import unittest
import zipfile
from unittest.mock import patch

from services.echosos_service import _blood_observations, extract_echosos_url, parse_echosos_data


URL = "https://eid.echosos.com/#b=1&f=Markus%20&g=euJH&i=&l=W%C3%B6ss%20&n1=Claudia%20Maria%20Enz%20W%C3%B6ss&p1=%2B41765771463"


class EchoSosServiceTests(unittest.TestCase):
    def test_decodes_echo_sos_fields(self):
        data = parse_echosos_data(URL)

        self.assertEqual(data["given"], "Markus")
        self.assertEqual(data["family"], "Wöss")
        self.assertEqual(data["birth_date"], "1966-09-07")
        self.assertEqual(data["blood_group"], "A+")
        self.assertEqual(data["emergency_contact"]["phone"], "+41765771463")

    def test_reads_pkpass_barcode(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("pass.json", json.dumps({"barcodes": [{"message": URL}]}))

        self.assertEqual(
            extract_echosos_url(output.getvalue(), "application/vnd.apple.pkpass"),
            URL,
        )

    @patch("services.echosos_service.validate_coding", return_value={"status": "validated"})
    def test_blood_observation_has_import_date_and_author(self, _validate_coding):
        observation = _blood_observations(
            {"blood_group": "A+", "source_url": URL},
            "3323",
            "test-user",
        )[0]

        self.assertEqual(observation["performer"][0]["display"], "test-user")
        self.assertEqual(
            observation["category"][0]["coding"][0]["code"],
            "laboratory",
        )
        self.assertTrue(observation["effectiveDateTime"].endswith("Z"))
        self.assertEqual(observation["issued"], observation["effectiveDateTime"])


if __name__ == "__main__":
    unittest.main()
