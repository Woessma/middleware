import copy
import io
import json
import unittest
import zipfile
from unittest.mock import Mock, patch

from services.echosos_service import (
    _blood_observations,
    _clinical_identity,
    _echosos_allergy_resources,
    _echosos_condition_resources,
    _echosos_organ_donation_consents,
    _patient_resource,
    _transaction_entry,
    extract_echosos_url,
    import_echosos,
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
    @patch("services.echosos_service.validate_coding", return_value={"status": "validated"})
    def test_all_generated_resource_identifiers_ignore_unrelated_qr_changes(self, _validate):
        data = parse_echosos_data(COMPACT_QR_URL)
        data["blood_group"] = "A+"
        changed = copy.deepcopy(data)
        changed["source_url"] += "&i=updated"
        changed["allergy_selections"].reverse()
        changed["medical_history_selections"].reverse()
        for builder in (
            lambda item: _blood_observations(item, "123", "patient"),
            lambda item: _echosos_organ_donation_consents(item, "123"),
            lambda item: _echosos_allergy_resources(item, "123"),
            lambda item: _echosos_condition_resources(item, "123"),
        ):
            with self.subTest(builder=builder):
                original = builder(data)
                updated = builder(changed)
                self.assertEqual(
                    sorted(item["identifier"][0]["value"] for item in original),
                    sorted(item["identifier"][0]["value"] for item in updated),
                )

    @patch("services.echosos_service.requests.get")
    @patch("services.echosos_service.validate_coding", return_value={"status": "validated"})
    def test_blood_and_consent_reuse_legacy_ids_without_merging_different_content(self, _validate, get):
        data = parse_echosos_data(URL + "&o=0")
        resources = _blood_observations(data, "123", "patient") + _echosos_organ_donation_consents(data, "123")
        for resource in resources:
            with self.subTest(resource_type=resource["resourceType"]):
                legacy = copy.deepcopy(resource)
                legacy["id"] = "legacy"
                legacy["identifier"][0]["value"] = "old-url"
                if resource["resourceType"] == "Observation":
                    legacy["effectiveDateTime"] = legacy["issued"] = "2020-01-01T00:00:00Z"
                different = copy.deepcopy(legacy)
                different["id"] = "different"
                if resource["resourceType"] == "Observation":
                    different["valueCodeableConcept"]["text"] = "B-"
                else:
                    different["provision"]["type"] = "deny"
                other_source = copy.deepcopy(legacy)
                other_source["identifier"][0]["system"] = "https://example.org/other"
                get.side_effect = [
                    Mock(json=lambda: {"entry": []}),
                    Mock(json=lambda: {"entry": [{"resource": item} for item in (different, other_source, legacy)]}),
                ]
                entry = _transaction_entry(resource)
                self.assertEqual(entry["request"], {"method": "PUT", "url": resource["resourceType"] + "/legacy"})
                self.assertIn(legacy["identifier"][0], resource["identifier"])
                if resource["resourceType"] == "Observation":
                    self.assertEqual(resource["effectiveDateTime"], "2020-01-01T00:00:00Z")
                    self.assertEqual(resource["issued"], resource["effectiveDateTime"])

    def test_patient_contacts_are_idempotent(self):
        data = parse_echosos_data(COMPACT_QR_URL)
        first = _patient_resource(data)
        self.assertEqual(_patient_resource(data, first), first)
        self.assertEqual(len(first["contact"]), 3)

    @patch("services.echosos_service.validate_coding", return_value={"status": "validated"})
    def test_blood_identity_only_ignores_echosos_import_timestamps(self, _validate):
        original = _blood_observations(parse_echosos_data(URL), "123", "patient")[0]
        changed_time = copy.deepcopy(original)
        changed_time["issued"] = changed_time["effectiveDateTime"] = "2020-01-01T00:00:00Z"
        self.assertEqual(_clinical_identity(original), _clinical_identity(changed_time))
        for item in (original, changed_time):
            item["identifier"][0]["system"] = "https://example.org/another-source"
        self.assertNotEqual(_clinical_identity(original), _clinical_identity(changed_time))

    @patch("services.echosos_service.validate_coding", return_value={"status": "validated"})
    def test_blood_and_consent_identifiers_separate_patients_and_values(self, _validate):
        data = parse_echosos_data(URL + "&o=0")
        for builder in (
            lambda item: _blood_observations(item, "123", "patient")[0],
            lambda item: _echosos_organ_donation_consents(item, "123")[0],
        ):
            original = builder(data)["identifier"]
            other = copy.deepcopy(data)
            other["birth_date"] = "1991-01-15"
            self.assertNotEqual(original, builder(other)["identifier"])
            other = copy.deepcopy(data)
            other["blood_group"] = "B-"
            other["organ_donation"]["outside_switzerland"] = "no"
            self.assertNotEqual(original, builder(other)["identifier"])

    def test_condition_identifier_ignores_url_changes_and_selection_order(self):
        data = parse_echosos_data(COMPACT_QR_URL)
        original = _echosos_condition_resources(data, "123")
        changed = copy.deepcopy(data)
        changed["source_url"] += "&i=changed"
        changed["medical_history_selections"].reverse()
        reordered = _echosos_condition_resources(changed, "123")
        self.assertEqual(
            {item["code"]["text"]: item["identifier"] for item in original},
            {item["code"]["text"]: item["identifier"] for item in reordered},
        )
        changed["birth_date"] = "1991-01-15"
        other_patient = _echosos_condition_resources(changed, "456")
        self.assertNotEqual(reordered[0]["identifier"], other_patient[0]["identifier"])

    @patch("services.echosos_service.requests.get")
    def test_condition_reimport_reuses_legacy_record_and_preserves_identifiers(self, get):
        condition = _echosos_condition_resources(parse_echosos_data(COMPACT_QR_URL), "123")[0]
        legacy = copy.deepcopy(condition)
        legacy["id"] = "old-1"
        legacy["identifier"][0]["value"] = "old-url-hash"
        duplicate = copy.deepcopy(legacy)
        duplicate["id"] = "old-2"
        duplicate["identifier"][0]["value"] = "another-old-url-hash"
        get.side_effect = [
            Mock(json=lambda: {"entry": []}),
            Mock(json=lambda: {"entry": [{"resource": duplicate}, {"resource": legacy}]}),
        ]

        entry = _transaction_entry(condition)

        self.assertEqual(entry["request"], {"method": "PUT", "url": "Condition/old-1"})
        self.assertIn(legacy["identifier"][0], entry["resource"]["identifier"])
        self.assertEqual(len(entry["resource"]["identifier"]), 2)
        self.assertEqual(get.call_args.kwargs["params"]["patient"], "Patient/123")

    @patch("services.echosos_service.requests.get")
    def test_condition_legacy_match_preserves_other_sources_patients_and_clinical_details(self, get):
        condition = _echosos_condition_resources(parse_echosos_data(COMPACT_QR_URL), "123")[0]
        other_source = copy.deepcopy(condition)
        other_source["identifier"][0]["system"] = "https://example.org/other"
        other_patient = copy.deepcopy(condition)
        other_patient["subject"]["reference"] = "Patient/456"
        other_status = copy.deepcopy(condition)
        other_status["clinicalStatus"] = {"coding": [{"code": "resolved"}]}
        get.side_effect = [
            Mock(json=lambda: {"entry": []}),
            Mock(json=lambda: {"entry": [
                {"resource": item} for item in (other_source, other_patient, other_status)
            ]}),
        ]

        entry = _transaction_entry(condition)

        self.assertEqual(entry["request"]["method"], "POST")
        self.assertIn("ifNoneExist", entry["request"])

    @patch("services.echosos_service.requests.get")
    def test_condition_reimport_uses_stable_identifier(self, get):
        condition = _echosos_condition_resources(parse_echosos_data(COMPACT_QR_URL), "123")[0]
        existing = copy.deepcopy(condition)
        existing["id"] = "existing"
        get.return_value = Mock(json=lambda: {"entry": [{"resource": existing}]})

        self.assertEqual(
            _transaction_entry(condition)["request"],
            {"method": "PUT", "url": "Condition/existing"},
        )
        get.assert_called_once()

    def test_allergy_identifier_ignores_url_changes_and_selection_order(self):
        data = parse_echosos_data(COMPACT_QR_URL)
        original = _echosos_allergy_resources(data, "123")
        changed = copy.deepcopy(data)
        changed["source_url"] += "&i=changed"
        changed["allergy_selections"].reverse()
        reordered = _echosos_allergy_resources(changed, "123")
        self.assertEqual(
            {item["code"]["text"]: item["identifier"] for item in original},
            {item["code"]["text"]: item["identifier"] for item in reordered},
        )
        changed["birth_date"] = "1991-01-15"
        other_patient = _echosos_allergy_resources(changed, "456")
        self.assertNotEqual(reordered[0]["identifier"], other_patient[0]["identifier"])

    @patch("services.echosos_service.requests.get")
    def test_reimport_reuses_legacy_allergy_and_preserves_identifiers(self, get):
        allergy = _echosos_allergy_resources(parse_echosos_data(COMPACT_QR_URL), "123")[0]
        legacy = copy.deepcopy(allergy)
        legacy["verificationStatus"]["coding"][0]["code"] = "confirmed"
        legacy.pop("asserter")
        legacy["id"] = "old-1"
        legacy["identifier"][0]["value"] = "old-url-hash"
        duplicate = copy.deepcopy(legacy)
        duplicate["id"] = "old-2"
        duplicate["identifier"][0]["value"] = "another-old-url-hash"
        get.side_effect = [
            Mock(json=lambda: {"entry": []}),
            Mock(json=lambda: {"entry": [{"resource": legacy}, {"resource": duplicate}]}),
        ]

        entry = _transaction_entry(allergy)

        self.assertEqual(entry["request"], {"method": "PUT", "url": "AllergyIntolerance/old-1"})
        self.assertEqual(len(entry["resource"]["identifier"]), 2)
        self.assertIn(legacy["identifier"][0], entry["resource"]["identifier"])
        self.assertEqual(get.call_args.kwargs["params"]["patient"], "Patient/123")

    @patch("services.echosos_service.requests.get")
    def test_legacy_match_does_not_merge_other_sources_or_different_reactions(self, get):
        allergy = _echosos_allergy_resources(parse_echosos_data(COMPACT_QR_URL), "123")[0]
        other_source = copy.deepcopy(allergy)
        other_source["id"] = "other-source"
        other_source["identifier"][0]["system"] = "https://example.org/other"
        other_reaction = copy.deepcopy(allergy)
        other_reaction["id"] = "other-reaction"
        other_reaction["reaction"] = []
        get.side_effect = [
            Mock(json=lambda: {"entry": []}),
            Mock(json=lambda: {"entry": [
                {"resource": other_source}, {"resource": other_reaction},
            ]}),
        ]

        entry = _transaction_entry(allergy)

        self.assertEqual(entry["request"]["method"], "POST")
        self.assertIn("ifNoneExist", entry["request"])

    @patch("services.echosos_service.requests.get")
    def test_reimport_uses_stable_identifier_without_legacy_search(self, get):
        allergy = _echosos_allergy_resources(parse_echosos_data(COMPACT_QR_URL), "123")[0]
        existing = copy.deepcopy(allergy)
        existing["id"] = "existing"
        get.return_value = Mock(json=lambda: {"entry": [{"resource": existing}]})

        entry = _transaction_entry(allergy)

        self.assertEqual(entry["request"], {"method": "PUT", "url": "AllergyIntolerance/existing"})
        get.assert_called_once()

    def test_patient_allergy_assertions_are_unconfirmed(self):
        for data in (
            parse_echosos_data(COMPACT_QR_URL),
            {"given": "Test", "family": "Example", "birth_date": "1990-01-01",
             "allergy_selections": [], "no_known_allergies": True},
        ):
            allergies = _echosos_allergy_resources(data, "123")
            self.assertTrue(allergies)
            for allergy in allergies:
                self.assertEqual(allergy["verificationStatus"]["coding"][0]["code"], "unconfirmed")
                self.assertEqual(allergy["asserter"], {"reference": "Patient/123"})

    @patch("services.echosos_service.requests.get")
    def test_reimport_preserves_existing_allergy_assessment_and_source(self, get):
        for status in ("confirmed", "refuted", "entered-in-error", "unconfirmed"):
            allergy = _echosos_allergy_resources(parse_echosos_data(COMPACT_QR_URL), "123")[0]
            existing = copy.deepcopy(allergy)
            existing["id"] = "existing"
            existing["verificationStatus"]["coding"][0]["code"] = status
            existing["asserter"] = {"reference": "Practitioner/doctor"}
            existing["recorder"] = {"reference": "Practitioner/recorder"}
            get.return_value = Mock(json=lambda: {"entry": [{"resource": existing}]})
            result = _transaction_entry(allergy)["resource"]
            for key in ("verificationStatus", "asserter", "recorder"):
                self.assertEqual(result[key], existing[key])

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
                "given": "Max",
                "family": "Beispiel",
                "birth_date": "1990-01-15",
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
                "given": "Max",
                "family": "Beispiel",
                "birth_date": "1990-01-15",
                "source_url": "https://eid.echosos.com/#d=L",
                "medical_history_selections": ["Nierenversagen/Dialyse"],
            },
            "123",
        )

        self.assertEqual(conditions[0]["code"], {"text": "Nierenversagen/Dialyse"})

    def test_builds_consent_for_explicit_organ_donation_choices_only(self):
        consent_data = {
            **parse_echosos_data(URL),
            "source_url": "https://eid.echosos.com/#o=0",
            "organ_donation": {"outside_switzerland": "yes", "swiss_registry": None},
        }

        yes_consent = _echosos_organ_donation_consents(consent_data, "123")[0]
        no_consent = _echosos_organ_donation_consents(
            {
                **parse_echosos_data(URL),
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
                **parse_echosos_data(URL),
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
            {**parse_echosos_data(URL), "blood_group": "A+", "source_url": URL},
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

    def test_import_returns_transaction_bundle_for_new_patient(self):
        data = {
            "given": "Eva",
            "family": "Beispiel",
            "birth_date": "1990-01-15",
            "source_url": URL,
            "blood_group": "A+",
            "emergency_contacts": [],
            "allergy_selections": [],
            "medical_history_selections": [],
            "organ_donation": {},
        }
        with (
            patch("services.echosos_service.extract_echosos_url", return_value=URL),
            patch("services.echosos_service.parse_echosos_data", return_value=data),
            patch("services.echosos_service._patient_search", return_value=None),
            patch("services.echosos_service._existing_resource_id", return_value=None),
            patch("services.echosos_service.validate_coding", return_value={"status": "validated"}),
            patch("services.echosos_service.requests.post") as post,
            patch("services.echosos_service.requests.put") as put,
        ):
            bundle = import_echosos(b"qr")

        patient_entry = bundle["entry"][0]
        patient_reference = patient_entry["fullUrl"]
        self.assertEqual(bundle["resourceType"], "Bundle")
        self.assertEqual(bundle["type"], "transaction")
        self.assertEqual(patient_entry["request"]["method"], "POST")
        self.assertEqual(patient_entry["request"]["url"], "Patient")
        self.assertIn("ifNoneExist", patient_entry["request"])
        self.assertEqual(bundle["entry"][1]["resource"]["subject"]["reference"], patient_reference)
        post.assert_not_called()
        put.assert_not_called()

    def test_import_updates_existing_patient_in_transaction_bundle(self):
        data = {
            "given": "Max",
            "family": "Beispiel",
            "birth_date": "1990-01-15",
            "source_url": COMPACT_QR_URL,
            "blood_group": None,
            "emergency_contacts": [],
            "allergy_selections": [{"allergen": "Penizillin", "reaction": None}],
            "no_known_allergies": False,
            "medical_history_selections": [],
            "organ_donation": {},
        }
        existing = {
            "resourceType": "Patient",
            "id": "123",
            "name": [{"family": "Beispiel", "given": ["Max"]}],
            "birthDate": "1990-01-15",
        }
        with (
            patch("services.echosos_service.extract_echosos_url", return_value=COMPACT_QR_URL),
            patch("services.echosos_service.parse_echosos_data", return_value=data),
            patch("services.echosos_service._patient_search", return_value=existing),
            patch("services.echosos_service._existing_resource_id", return_value=None),
            patch("services.echosos_service.requests.post") as post,
            patch("services.echosos_service.requests.put") as put,
        ):
            bundle = import_echosos(b"qr")

        self.assertEqual(bundle["entry"][0]["request"], {"method": "PUT", "url": "Patient/123"})
        self.assertEqual(bundle["entry"][1]["resource"]["patient"]["reference"], "Patient/123")
        post.assert_not_called()
        put.assert_not_called()


if __name__ == "__main__":
    unittest.main()
