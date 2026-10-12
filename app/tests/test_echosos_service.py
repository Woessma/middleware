import io
import json
import unittest
import zipfile
from unittest.mock import patch

from services.echosos_service import (
    _blood_observations,
    _echosos_allergy_resources,
    _echosos_condition_resources,
    _echosos_organ_donation_consents,
    _patient_resource,
    extract_echosos_url,
    parse_echosos_data,
)
from terminology.echosos import (
    ECHOSOS_ALLERGENS,
    ECHOSOS_ALLERGENS_REQUIRING_CONFIRMATION,
    ECHOSOS_ALLERGY_OPTIONS_WITHOUT_CODE,
    ECHOSOS_ALLERGY_REACTIONS,
    ECHOSOS_MEDICAL_HISTORY,
    SNOMED_SYSTEM,
)


URL = (
    "https://eid.echosos.com/#b=1&f=Eva&g=fGBP&i=&l=Beispiel"
    "&n1=Notfallkontakt&p1=%2B41000000000"
)
COMPACT_QR_URL = (
    "https://eid.echosos.com/#a=BHKL&b=8&d=BS&f=Max&g=fGBP&l=Beispiel"
    "&m=BG&n1=Kontakt%201&p1=%2B41000000001"
    "&n2=Kontakt%202&p2=%2B41000000002"
    "&n3=Kontakt%203&p3=%2B41000000003&o=0&r=ACAE"
)


class EchoSosServiceTests(unittest.TestCase):
    def test_medical_history_mapping_uses_only_snomed(self):
        self.assertEqual(len(ECHOSOS_MEDICAL_HISTORY), 17)

        for mapping in ECHOSOS_MEDICAL_HISTORY.values():
            codings = mapping.get("alternatives", (mapping,))
            self.assertTrue(codings)
            self.assertTrue(all(coding["system"] == SNOMED_SYSTEM for coding in codings))

        self.assertTrue(
            ECHOSOS_MEDICAL_HISTORY["Nierenversagen/Dialyse"]["requires_disambiguation"]
        )
        self.assertTrue(
            ECHOSOS_MEDICAL_HISTORY["Herzschrittmacher/Defibrillator"]["requires_disambiguation"]
        )

    def test_allergy_mapping_uses_only_snomed(self):
        self.assertEqual(sum(len(options) for options in ECHOSOS_ALLERGENS.values()), 12)
        self.assertEqual(len(ECHOSOS_ALLERGY_REACTIONS), 5)

        for category in ECHOSOS_ALLERGENS.values():
            for coding in category.values():
                if coding is not None:
                    self.assertEqual(coding["system"], SNOMED_SYSTEM)

        self.assertTrue(
            all(coding["system"] == SNOMED_SYSTEM for coding in ECHOSOS_ALLERGY_REACTIONS.values())
        )
        self.assertEqual(ECHOSOS_ALLERGENS["Weitere"]["Andere"], None)
        self.assertIn("Keine", ECHOSOS_ALLERGY_OPTIONS_WITHOUT_CODE)
        self.assertTrue(ECHOSOS_ALLERGENS_REQUIRING_CONFIRMATION)

    def test_decodes_echo_sos_fields(self):
        data = parse_echosos_data(URL)

        self.assertEqual(data["given"], "Eva")
        self.assertEqual(data["family"], "Beispiel")
        self.assertEqual(data["birth_date"], "1990-01-15")
        self.assertEqual(data["blood_group"], "A+")
        self.assertEqual(data["emergency_contact"]["phone"], "+41000000000")

    def test_decodes_synthetic_qr_image_fixture(self):
        image_path = __file__.replace(
            "test_echosos_service.py",
            "data/EchoSOS.synthetic.png",
        )
        with open(image_path, "rb") as image_file:
            url = extract_echosos_url(image_file.read(), "image/png")

        data = parse_echosos_data(url)

        self.assertEqual(data["given"], "Max")
        self.assertEqual(data["family"], "Beispiel")
        self.assertEqual(data["birth_date"], "1990-01-15")
        self.assertEqual(len(data["allergy_selections"]), 4)
        self.assertEqual(len(data["medical_history_selections"]), 2)

    def test_decodes_compact_qr_selections_and_all_emergency_contacts(self):
        data = parse_echosos_data(COMPACT_QR_URL)

        self.assertEqual(data["blood_group"], "Unbekannt")
        self.assertEqual(
            data["allergy_selections"],
            [
                {"allergen": "Penizillin", "reaction": "Hautrötung"},
                {"allergen": "Erdnüsse", "reaction": "Atemnot"},
                {"allergen": "Bienenstich", "reaction": "Hautrötung"},
                {"allergen": "Wespenstich", "reaction": "Anaphylaxie"},
            ],
        )
        self.assertEqual(data["medication_selections"], ["Antihypertensiva", "Antidepressiva"])
        self.assertEqual(data["medical_history_selections"], ["Asthma", "Diabetes"])
        self.assertEqual(data["organ_donation"]["outside_switzerland"], "yes")
        self.assertEqual(len(data["emergency_contacts"]), 3)
        self.assertEqual(data["emergency_contacts"][2]["name"], "Kontakt 3")

        patient = _patient_resource(data)
        self.assertEqual(len(patient["contact"]), 3)
        self.assertEqual(
            [contact["name"]["text"] for contact in patient["contact"]],
            ["Kontakt 1", "Kontakt 2", "Kontakt 3"],
        )

    def test_builds_fhir_allergies_with_snomed_reaction_and_patient_recorder(self):
        data = parse_echosos_data(COMPACT_QR_URL)

        allergies = _echosos_allergy_resources(data, "123")

        self.assertEqual(len(allergies), 4)
        self.assertEqual(allergies[0]["resourceType"], "AllergyIntolerance")
        self.assertEqual(allergies[0]["code"]["coding"][0]["system"], SNOMED_SYSTEM)
        self.assertEqual(
            allergies[0]["reaction"][0]["manifestation"][0]["coding"][0]["code"],
            ECHOSOS_ALLERGY_REACTIONS["Hautrötung"]["code"],
        )
        self.assertEqual(allergies[0]["recorder"]["reference"], "Patient/123")

    def test_builds_fhir_conditions_with_snomed_and_patient_asserter(self):
        data = parse_echosos_data(COMPACT_QR_URL)

        conditions = _echosos_condition_resources(data, "123")

        self.assertEqual(len(conditions), 2)
        self.assertEqual(conditions[0]["resourceType"], "Condition")
        self.assertEqual(conditions[0]["code"]["coding"][0]["system"], SNOMED_SYSTEM)
        self.assertEqual(conditions[0]["asserter"]["reference"], "Patient/123")

    def test_builds_no_known_allergy_as_snomed_absence_assertion(self):
        allergies = _echosos_allergy_resources(
            {
                "source_url": "https://eid.echosos.com/#a=A",
                "allergy_selections": [],
                "no_known_allergies": True,
            },
            "123",
        )

        self.assertEqual(len(allergies), 1)
        self.assertEqual(allergies[0]["code"]["coding"][0]["code"], "716186003")
        self.assertEqual(allergies[0]["code"]["coding"][0]["system"], SNOMED_SYSTEM)

    def test_preserves_combined_history_label_without_asserting_both_snomed_alternatives(self):
        conditions = _echosos_condition_resources(
            {
                "source_url": "https://eid.echosos.com/#d=L",
                "medical_history_selections": ["Nierenversagen/Dialyse"],
            },
            "123",
        )

        self.assertEqual(conditions[0]["code"], {"text": "Nierenversagen/Dialyse"})

    def test_builds_consent_for_explicit_organ_donation_choices_only(self):
        consent_data = {
            "source_url": "https://eid.echosos.com/#o=0",
            "organ_donation": {"outside_switzerland": "yes", "swiss_registry": None},
        }

        yes_consent = _echosos_organ_donation_consents(consent_data, "123")[0]
        no_consent = _echosos_organ_donation_consents(
            {
                "source_url": "https://eid.echosos.com/#o=1",
                "organ_donation": {"outside_switzerland": "no", "swiss_registry": None},
            },
            "123",
        )[0]

        self.assertEqual(yes_consent["resourceType"], "Consent")
        self.assertEqual(yes_consent["scope"]["coding"][0]["code"], "adr")
        self.assertEqual(yes_consent["category"][0]["coding"][0]["code"], "42348-3")
        self.assertEqual(yes_consent["patient"]["reference"], "Patient/123")
        self.assertEqual(yes_consent["performer"][0]["reference"], "Patient/123")
        self.assertEqual(yes_consent["provision"]["type"], "permit")
        self.assertEqual(no_consent["provision"]["type"], "deny")
        self.assertNotEqual(yes_consent["identifier"], no_consent["identifier"])

        for status in ("no_information", None):
            self.assertEqual(
                _echosos_organ_donation_consents(
                    {
                        "source_url": "https://eid.echosos.com/#o=2",
                        "organ_donation": {
                            "outside_switzerland": status,
                            "swiss_registry": None,
                        },
                    },
                    "123",
                ),
                [],
            )

        self.assertEqual(
            _echosos_organ_donation_consents(
                {
                    "source_url": "https://eid.echosos.com/#s=1",
                    "organ_donation": {
                        "outside_switzerland": None,
                        "swiss_registry": "no_entry",
                    },
                },
                "123",
            ),
            [],
        )
        swiss_registry_consent = _echosos_organ_donation_consents(
            {
                "source_url": "https://eid.echosos.com/#s=0",
                "organ_donation": {
                    "outside_switzerland": None,
                    "swiss_registry": "registered",
                },
            },
            "123",
        )[0]
        self.assertEqual(swiss_registry_consent["provision"]["type"], "permit")

    def test_reads_pkpass_barcode(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("pass.json", json.dumps({"barcodes": [{"message": URL}]}))

        self.assertEqual(
            extract_echosos_url(output.getvalue(), "application/vnd.apple.pkpass"),
            URL,
        )

    @patch("services.echosos_service.validate_coding", return_value={"status": "validated"})
    def test_blood_observation_has_import_date_and_patient_performer(self, _validate_coding):
        observation = _blood_observations(
            {"blood_group": "A+", "source_url": URL},
            "3323",
            "test-user",
        )[0]

        self.assertEqual(observation["performer"][0]["reference"], "Patient/3323")
        self.assertEqual(
            observation["category"][0]["coding"][0]["code"],
            "laboratory",
        )
        self.assertTrue(observation["effectiveDateTime"].endswith("Z"))
        self.assertEqual(observation["issued"], observation["effectiveDateTime"])


if __name__ == "__main__":
    unittest.main()
