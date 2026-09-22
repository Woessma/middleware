import io
import json
import unittest
import zipfile

from services.card_analysis_service import analyze_card, _parse_ocr_card_text

URL = "https://eid.echosos.com/#b=1&f=Markus%20&g=euJH&i=&l=W%C3%B6ss%20&n1=Claudia%20Maria%20Enz%20W%C3%B6ss&p1=%2B41765771463"


class CardAnalysisServiceTests(unittest.TestCase):
    def test_analyzes_echo_sos_qr_text(self):
        result = analyze_card(URL.encode("utf-8"))

        self.assertEqual(result["person"]["given"], "Markus")
        self.assertEqual(result["person"]["family"], "Wöss")
        self.assertEqual(result["person"]["birth_date"], "1966-09-07")
        self.assertEqual(result["card_type"], "echo_sos_qr")
        self.assertTrue(any(item["system"].endswith("echosos") for item in result["identifiers"]))

    def test_analyzes_pkpass_barcode(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("pass.json", json.dumps({"barcodes": [{"message": URL}]}))

        result = analyze_card(output.getvalue(), content_type="application/vnd.apple.pkpass")

        self.assertEqual(result["card_type"], "echo_sos_qr")
        self.assertEqual(result["person"]["given"], "Markus")
        self.assertEqual(result["person"]["family"], "Wöss")

    def test_analyzes_generic_card_text(self):
        payload = "family=Muster\ngiven=Anna\nbirth_date=1990-05-21\nidentifier=A123456"

        result = analyze_card(payload.encode("utf-8"))

        self.assertEqual(result["card_type"], "generic_card")
        self.assertEqual(result["person"]["family"], "Muster")
        self.assertEqual(result["person"]["given"], "Anna")
        self.assertEqual(result["person"]["birth_date"], "1990-05-21")
        self.assertEqual(result["identifiers"][0]["value"], "A123456")

    def test_analyzes_mrz_like_card_text(self):
        payload = "P<MUSTER<<ANNA<<<<<<<<<<<<<<<<<<\n9905215F2601012<<<<<<<<<<<<<<<<<"

        result = analyze_card(payload.encode("utf-8"))

        self.assertEqual(result["card_type"], "mrz_card")
        self.assertEqual(result["person"]["family"], "MUSTER")
        self.assertEqual(result["person"]["given"], "ANNA")
        self.assertEqual(result["person"]["birth_date"], "1999-05-21")

    def test_normalizes_insurance_card_ocr_fields(self):
        ocr_text = """Nachname: Muster
Vorname: Anna
Geburtsdatum: 21.05.1990
Versichertennummer: A 123 456
Krankenkasse: Beispiel Kasse"""

        result = _parse_ocr_card_text(ocr_text)

        self.assertEqual(result["card_type"], "insurance_card_ocr")
        self.assertEqual(result["person"]["family"], "Muster")
        self.assertEqual(result["person"]["given"], "Anna")
        self.assertEqual(result["person"]["birth_date"], "1990-05-21")
        self.assertEqual(result["identifiers"][0]["value"], "A123456")
        self.assertEqual(result["identifiers"][1]["value"], "Beispiel Kasse")

    def test_ignores_ocr_field_labels_as_names(self):
        ocr_text = """3. Name OOS
4. Vornamen = Geburtsdatu è
MARKUS 07/09/1966
756.4582.5336.44 0881 - EGK
80756008810013298945 31/03/2027"""

        result = _parse_ocr_card_text(ocr_text)

        self.assertEqual(result["person"]["given"], "Markus")
        self.assertEqual(result["person"]["birth_date"], "1966-09-07")

    def test_normalizes_insurance_card_name_case_and_number_noise(self):
        ocr_text = """wöss
MARKUS 07/09/1966
Versicherten-Nummer: 00196760 CH
80756008810013298945 31/03/2027"""

        result = _parse_ocr_card_text(ocr_text)

        self.assertEqual(result["person"]["family"], "Wöss")
        self.assertEqual(result["person"]["given"], "Markus")
        self.assertEqual(result["identifiers"][0]["value"], "00196760")


if __name__ == "__main__":
    unittest.main()
