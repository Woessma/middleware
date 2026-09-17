import unittest
from unittest.mock import patch

from parser.hl7v2.oru_r01_parser import parse_oru_r01, to_transaction_bundle
from services.terminology_service import validate_bundle_terminology


MESSAGE = "\r".join([
    "MSH|^~\\&|ULZH|Befund|MWST1|SP|20260107153030||ORU^R01|2601071530_00001|P|2.4",
    "PID|0001|UZ726135100123|LUTLF9V92B76VNP||Matterhorn^Heinz||19780308|M|||^^Luzern^^6000^CH|||||||DI98748399",
    "PV1|0001|I|MWST1",
    "OBR|0001|1402000001|1402000001|||20260107133000||||||||20260107133500||MWST1||||||||||F",
    "OBX|0001|NM|1742-6^Alanine aminotransferase^LN^ALAT^ALAT (GPT)^99LOCAL||22|U/L|<50|N|||F|||20260107140001",
    "OBX|0002|NM|1920-8^Aspartate aminotransferase^LN^ASAT^ASAT (GOT)^99LOCAL||18|U/L|<35|N|||F|||20260107140001",
    "OBX|0003|NM|2951-2^Sodium^LN^NA^Natrium^99LOCAL||141|mmol/L|136-145|N|||F|||20260107140500",
])


class Hl7v2OruR01Tests(unittest.TestCase):
    def test_converts_patient_and_loinc_observations(self):
        bundle = parse_oru_r01(MESSAGE)
        resources = [entry["resource"] for entry in bundle["entry"]]
        observations = [resource for resource in resources if resource["resourceType"] == "Observation"]

        self.assertEqual(len(observations), 3)
        self.assertEqual(resources[0]["resourceType"], "Patient")
        self.assertEqual(resources[0]["id"], "hl7-LUTLF9V92B76VNP")
        self.assertEqual(resources[0]["name"][0]["family"], "Matterhorn")
        self.assertEqual(resources[0]["birthDate"], "1978-03-08")
        self.assertEqual(observations[0]["code"]["coding"][0]["system"], "http://loinc.org")
        self.assertEqual(observations[0]["valueQuantity"]["value"], 22.0)
        self.assertEqual(observations[0]["referenceRange"][0]["text"], "<50")

    def test_observation_ids_are_stable_and_duplicate_obx_is_removed(self):
        message = "\r".join([
            "MSH|^~\\&|LAB|ORG|CLIN|HOSP|202601141326||ORU^R01|MSG1|P|2.4",
            "PID|1||123456^^^HOSP^MR||Mustermann^Erika||19800512|F",
            "OBR|1|ORD|RES|24323-8^Basic Metabolic Panel^LN|R||202601141200",
            "OBX|1|NM|2345-7^Glucose^LN||5.1|mmol/L|3.9-5.5|N|||F",
            "OBX|1|NM|2345-7^Glucose^LN||5.1|mmol/L|3.9-5.5|N|||F",
        ])

        first_bundle = parse_oru_r01(message)
        second_bundle = parse_oru_r01(message)
        first_observations = [entry["resource"] for entry in first_bundle["entry"] if entry["resource"]["resourceType"] == "Observation"]
        second_observations = [entry["resource"] for entry in second_bundle["entry"] if entry["resource"]["resourceType"] == "Observation"]

        self.assertEqual(len(first_observations), 1)
        self.assertEqual(first_observations[0]["id"], second_observations[0]["id"])
        self.assertEqual(first_observations[0]["identifier"], second_observations[0]["identifier"])

    def test_converts_collection_to_idempotent_transaction_bundle(self):
        collection = parse_oru_r01(MESSAGE)
        transaction = to_transaction_bundle(collection)

        self.assertEqual(transaction["type"], "transaction")
        self.assertEqual(len(transaction["entry"]), 4)
        self.assertTrue(all(
            entry["request"]["method"] == "PUT"
            and entry["request"]["url"] == (
                f"{entry['resource']['resourceType']}/{entry['resource']['id']}"
            )
            for entry in transaction["entry"]
        ))
        self.assertEqual(transaction["entry"][0]["request"]["url"], "Patient/hl7-LUTLF9V92B76VNP")
        self.assertTrue(all(
            entry["resource"].get("text", {}).get("status") == "generated"
            for entry in transaction["entry"]
        ))

    def test_converts_two_panels_and_uses_obr_time_when_obx_time_is_missing(self):
        message = "\r".join([
            "MSH|^~\\&|LABSYS|LABORG|CLINIC|HOSPITAL|202601141326||ORU^R01|MSG00001|P|2.4",
            "PID|1||123456^^^HOSP^MR||Mustermann^Erika||19800512|F|||Musterstrasse 12^^Zürich^^8004||+41-44-5556677",
            "PV1|1|O|AMB^01^01",
            "ORC|RE|ORD998877|||",
            "OBR|1|ORD998877|RES998877|57021-8^CBC with Differential^LN|R||202601141200",
            "OBX|1|NM|6690-2^Leukocytes (WBC)^LN||7.8|10^9/L|3.5-10.5|N|||F",
            "OBX|2|NM|789-8^Erythrocytes (RBC)^LN||4.65|10^12/L|3.9-5.2|N|||F",
            "OBX|3|NM|718-7^Hemoglobin^LN||13.6|g/dL|12.0-16.0|N|||F",
            "OBX|4|NM|4544-3^Hematocrit^LN||40.2|%|36-46|N|||F",
            "OBX|5|NM|777-3^Platelets^LN||245|10^9/L|150-400|N|||F",
            "OBX|6|NM|736-9^MCV^LN||86|fL|80-96|N|||F",
            "OBX|7|NM|785-6^MCH^LN||29.2|pg|27-33|N|||F",
            "OBX|8|NM|786-4^MCHC^LN||34.0|g/dL|32-36|N|||F",
            "ORC|RE|ORD998878|||",
            "OBR|2|ORD998878|RES998878|24323-8^Basic Metabolic Panel^LN|R||202601141200",
            "OBX|9|NM|2345-7^Glucose^LN||5.1|mmol/L|3.9-5.5|N|||F",
            "OBX|10|NM|2160-0^Creatinine^LN||78|µmol/L|45-84|N|||F",
            "OBX|11|NM|2951-2^Sodium^LN||140|mmol/L|135-145|N|||F",
            "OBX|12|NM|2823-3^Potassium^LN||4.2|mmol/L|3.5-5.1|N|||F",
            "OBX|13|NM|2075-0^Chloride^LN||103|mmol/L|98-107|N|||F",
            "OBX|14|NM|2028-9^Calcium^LN||2.32|mmol/L|2.20-2.55|N|||F",
            "OBX|15|NM|3094-0^Urea Nitrogen (BUN)^LN||4.8|mmol/L|2.5-7.5|N|||F",
        ])

        bundle = parse_oru_r01(message)
        resources = [entry["resource"] for entry in bundle["entry"]]
        observations = [resource for resource in resources if resource["resourceType"] == "Observation"]

        self.assertEqual(len(observations), 15)
        self.assertTrue(all(
            observation["code"]["coding"][0]["system"] == "http://loinc.org"
            for observation in observations
        ))
        self.assertEqual(resources[0]["identifier"][0]["value"], "123456")
        self.assertEqual(resources[0]["id"], "hl7-123456")
        self.assertEqual(resources[0]["birthDate"], "1980-05-12")
        self.assertEqual(resources[0]["telecom"][0]["value"], "+41-44-5556677")
        self.assertEqual(observations[0]["effectiveDateTime"], "2026-01-14T12:00:00Z")
        self.assertEqual(observations[9]["code"]["coding"][0]["code"], "2160-0")
        self.assertTrue(all(
            observation["category"][0]["coding"][0]["code"] == "laboratory"
            for observation in observations
        ))

    @patch("services.terminology_service.validate_coding")
    def test_validates_all_obx_ln_codes_through_tx(self, mock_validate):
        mock_validate.return_value = {"status": "validated", "result": {}}

        bundle = parse_oru_r01("\r".join([
            "MSH|^~\\&|LAB|ORG|CLIN|HOSP|202601141326||ORU^R01|MSG1|P|2.4",
            "PID|1||123456^^^HOSP^MR||Mustermann^Erika||19800512|F",
            "OBR|1|ORD|RES|24323-8^Basic Metabolic Panel^LN|R||202601141200",
            "OBX|1|NM|2345-7^Glucose^LN||5.1|mmol/L|3.9-5.5|N|||F",
            "OBX|2|NM|2951-2^Sodium^LN||140|mmol/L|135-145|N|||F",
            "OBX|3|NM|2823-3^Potassium^LN||4.2|mmol/L|3.5-5.1|N|||F",
        ]))

        report = validate_bundle_terminology(bundle)
        validated_codes = {
            call.args[0]["code"]
            for call in mock_validate.call_args_list
            if call.args[0].get("system") == "http://loinc.org"
        }

        self.assertEqual(report["status"], "ok")
        self.assertEqual(validated_codes, {"2345-7", "2951-2", "2823-3"})

    @patch("services.terminology_service.validate_coding")
    def test_marks_glucose_code_as_loinc_for_tx_validation(self, mock_validate):
        mock_validate.return_value = {"status": "validated", "result": {}}
        message = "\r".join([
            "MSH|^~\\&|LAB|ORG|CLIN|HOSP|202601141326||ORU^R01|MSG1|P|2.4",
            "PID|1||123456^^^HOSP^MR||Mustermann^Erika||19800512|F",
            "OBR|1|ORD|RES|24323-8^Basic Metabolic Panel^LN|R||202601141200",
            "OBX|9|NM|2345-7^Glucose^LN||5.1|mmol/L|3.9-5.5|N|||F",
        ])

        bundle = parse_oru_r01(message)
        coding = bundle["entry"][1]["resource"]["code"]["coding"][0]
        report = validate_bundle_terminology(bundle)

        self.assertEqual(coding, {
            "system": "http://loinc.org",
            "code": "2345-7",
            "display": "Glucose",
        })
        self.assertEqual(report["status"], "ok")
        self.assertIn(
            (
                coding,
                {
                    "base_url": "https://tx.fhir.ch/r4",
                    "timeout": 30,
                },
            ),
            [
                (call.args[0], call.kwargs)
                for call in mock_validate.call_args_list
            ],
        )

    def test_preserves_local_code_without_claiming_it_is_loinc(self):
        message = " ".join([
            "MSH|^~\\&|ULZH|Befund|MWST1|SP|20260107150120||ORU^R01|MSG1|P|2.4",
            "PID|0001|UZ726135100096|3778704||Test^POST IT||19750101|M|||Teststrasse 99^^Dübendorf^^8600^CH",
            "PV1|0001|I|MWST1",
            "ORC||1401963494|1401963494||CM||||20260107150110",
            "OBR|0001|1401963494|1401963494|||20260107114400||||||||20260107135127||MWST1||||||||||F",
            "OBX|0001|NM|NA^Natrium||60|mmol/l|136-145|LL|||F|||20260107150119",
        ])

        bundle = parse_oru_r01(message)
        observation = bundle["entry"][1]["resource"]
        coding = observation["code"]["coding"][0]

        self.assertEqual(coding["system"], "https://woess.ch/fhir/CodeSystem/hl7v2-local")
        self.assertEqual(coding["code"], "NA")
        self.assertEqual(coding["display"], "Natrium")
        self.assertEqual(observation["valueQuantity"]["value"], 60.0)
        self.assertEqual(observation["valueQuantity"]["unit"], "mmol/l")
        self.assertEqual(observation["interpretation"][0]["coding"][0]["code"], "LL")


if __name__ == "__main__":
    unittest.main()