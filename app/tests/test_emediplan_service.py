import base64
import gzip
import json
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import Mock, patch

from services.emediplan_service import (
    emediplan_to_fhir_bundle,
    fhir_medications_to_epic_cda,
    fetch_medication_bundle_from_fhir_server,
    import_emediplan_to_fhir_server,
    import_bundle_to_fhir_server,
)


class EmediplanServiceTests(unittest.TestCase):
    def _sample_emediplan_object(self):
        return {
            "Id": "plan-1",
            "Auth": "7601000000000",
            "Dt": "2026-07-29T09:15:00+02:00",
            "MedType": 1,
            "Patient": {
                "FName": "Max",
                "LName": "Muster",
                "BDt": "1980-01-01",
                "Gender": 1,
                "Street": "Musterweg 1",
                "Zip": "3000",
                "City": "Bern",
                "Phone": "+41580000000",
                "Ids": [
                    {
                        "Type": 1,
                        "Val": "756.1234.5678.97",
                    }
                ],
            },
            "Medicaments": [
                {
                    "Id": "7680123456789",
                    "IdType": 2,
                    "Unit": "STK",
                    "TkgRsn": "Hypertonie",
                    "AppInstr": "Nach dem Essen",
                    "Pos": [
                        {
                            "DtFrom": "2026-07-01",
                            "DtTo": "2026-12-31",
                            "D": [1, 0, 1, 0],
                        }
                    ],
                }
            ],
        }

    @patch("services.emediplan_service.lookup_gln")
    def test_convert_creates_ch_core_practitioner_with_gln_oid(self, mock_lookup):
        mock_lookup.return_value = None
        payload = self._sample_emediplan_object()
        payload["Medicaments"][0]["PrscbBy"] = "7601009545993"

        bundle = emediplan_to_fhir_bundle(json.dumps(payload).encode("utf-8"))

        practitioner = next(
            entry["resource"]
            for entry in bundle["entry"]
            if entry["resource"]["resourceType"] == "Practitioner"
        )
        statement = next(
            entry["resource"]
            for entry in bundle["entry"]
            if entry["resource"]["resourceType"] == "MedicationStatement"
        )
        self.assertEqual(
            practitioner["meta"]["profile"],
            ["http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-practitioner"],
        )
        self.assertEqual(
            practitioner["identifier"],
            [{"system": "urn:oid:2.51.1.3", "value": "7601009545993"}],
        )
        self.assertEqual(
            statement["informationSource"]["reference"],
            f"Practitioner/{practitioner['id']}",
        )

    def _sample_chmed16a_payload(self):
        obj = self._sample_emediplan_object()
        data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        compressed = gzip.compress(data)
        encoded = base64.b64encode(compressed).decode("ascii")
        return f"CHMED16A1{encoded}".encode("utf-8")

    def test_convert_chmed16a_payload_to_fhir_bundle(self):
        bundle = emediplan_to_fhir_bundle(self._sample_chmed16a_payload())

        self.assertEqual(bundle["resourceType"], "Bundle")
        self.assertEqual(bundle["type"], "collection")
        self.assertEqual(
            bundle["identifier"],
            {
                "system": "https://emediplan.ch/fhir/NamingSystem/emediplan-plan-id",
                "value": "plan-1",
            },
        )

        resources = [entry["resource"] for entry in bundle["entry"]]
        resource_types = [resource["resourceType"] for resource in resources]

        self.assertIn("Patient", resource_types)
        self.assertIn("Medication", resource_types)
        self.assertIn("MedicationStatement", resource_types)

        statement = next(
            resource
            for resource in resources
            if resource["resourceType"] == "MedicationStatement"
        )

        self.assertEqual(statement["status"], "active")
        self.assertIn("medicationReference", statement)

    def test_create_epic_cda_from_fhir_bundle(self):
        med_object_json = json.dumps(self._sample_emediplan_object()).encode("utf-8")
        bundle = emediplan_to_fhir_bundle(med_object_json)

        cda_xml = fhir_medications_to_epic_cda(bundle)

        self.assertTrue(cda_xml.startswith("<?xml"))

        ns = {"hl7": "urn:hl7-org:v3"}
        root = ET.fromstring(cda_xml)

        section_code = root.find(
            ".//hl7:section/hl7:code",
            ns,
        )

        self.assertIsNotNone(section_code)
        self.assertEqual(section_code.attrib.get("code"), "10160-0")

        entries = root.findall(
            ".//hl7:section/hl7:entry/hl7:substanceAdministration",
            ns,
        )
        self.assertEqual(len(entries), 1)

    def test_epic_cda_includes_extended_patient_role_demographics(self):
        bundle = {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": "p1",
                        "identifier": [
                            {
                                "system": "urn:oid:2.16.756.5.32",
                                "value": "7560528012402",
                            }
                        ],
                        "name": [
                            {
                                "family": "Matter",
                                "given": ["Maxima"],
                            }
                        ],
                        "birthDate": "1981-01-12",
                        "gender": "female",
                        "address": [
                            {
                                "line": ["Testhausenstrasse 5"],
                                "postalCode": "3000",
                                "city": "Bern",
                                "state": "BE",
                                "country": "CHE",
                            }
                        ],
                        "telecom": [
                            {
                                "system": "phone",
                                "value": "+41769999999999",
                                "use": "mobile",
                            },
                            {
                                "system": "email",
                                "value": "maxima.matter@example.org",
                            },
                        ],
                    }
                },
                {
                    "resource": {
                        "resourceType": "Medication",
                        "id": "m1",
                        "code": {
                            "text": "Test Med",
                        },
                    }
                },
                {
                    "resource": {
                        "resourceType": "MedicationStatement",
                        "id": "ms1",
                        "status": "active",
                        "subject": {"reference": "Patient/p1"},
                        "medicationReference": {"reference": "Medication/m1"},
                    }
                },
            ],
        }

        cda_xml = fhir_medications_to_epic_cda(bundle)

        ns = {
            "hl7": "urn:hl7-org:v3",
        }
        root = ET.fromstring(cda_xml)

        patient_role = root.find(".//hl7:recordTarget/hl7:patientRole", ns)
        self.assertIsNotNone(patient_role)

        patient_id = root.find(
            ".//hl7:recordTarget/hl7:patientRole/hl7:id",
            ns,
        )
        self.assertIsNotNone(patient_id)
        self.assertEqual(patient_id.attrib.get("root"), "urn:oid:2.16.756.5.32")
        self.assertEqual(patient_id.attrib.get("extension"), "7560528012402")

        street = root.find(
            ".//hl7:recordTarget/hl7:patientRole/hl7:addr/hl7:streetAddressLine",
            ns,
        )
        self.assertIsNotNone(street)
        self.assertEqual(street.text, "Testhausenstrasse 5")

        telecom_values = {
            item.attrib.get("value")
            for item in root.findall(
                ".//hl7:recordTarget/hl7:patientRole/hl7:telecom",
                ns,
            )
        }
        self.assertIn("tel:+41769999999999", telecom_values)
        self.assertIn("mailto:maxima.matter@example.org", telecom_values)

    def test_epic_cda_contains_code_translations_for_multiple_codings(self):
        bundle = {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": "p1",
                        "name": [{"family": "Muster", "given": ["Max"]}],
                        "birthDate": "1980-01-01",
                    }
                },
                {
                    "resource": {
                        "resourceType": "Medication",
                        "id": "m1",
                        "code": {
                            "coding": [
                                {
                                    "system": "urn:epc:id:sgtin",
                                    "code": "7680485780715",
                                    "display": "Torem 10, Tabletten",
                                },
                                {
                                    "system": "https://emediplan.ch/fhir/NamingSystem/pharmacode",
                                    "code": "1551274",
                                    "display": "1551274",
                                },
                                {
                                    "system": "http://snomed.info/sct",
                                    "code": "27658006",
                                    "display": "Amoxicillin (substance)",
                                },
                            ],
                            "text": "Torem 10, Tabletten",
                        },
                    }
                },
                {
                    "resource": {
                        "resourceType": "MedicationStatement",
                        "id": "ms1",
                        "status": "active",
                        "subject": {"reference": "Patient/p1"},
                        "medicationReference": {"reference": "Medication/m1"},
                    }
                },
            ],
        }

        cda_xml = fhir_medications_to_epic_cda(bundle)
        ns = {"hl7": "urn:hl7-org:v3"}
        root = ET.fromstring(cda_xml)

        code_node = root.find(
            ".//hl7:manufacturedMaterial/hl7:code",
            ns,
        )

        self.assertIsNotNone(code_node)
        self.assertEqual(code_node.attrib.get("code"), "7680485780715")
        self.assertEqual(code_node.attrib.get("codeSystem"), "urn:epc:id:sgtin")

        translations = root.findall(
            ".//hl7:manufacturedMaterial/hl7:code/hl7:translation",
            ns,
        )

        self.assertEqual(len(translations), 2)

        translation_pairs = {
            (item.attrib.get("codeSystem"), item.attrib.get("code"))
            for item in translations
        }

        self.assertIn(
            (
                "https://emediplan.ch/fhir/NamingSystem/pharmacode",
                "1551274",
            ),
            translation_pairs,
        )
        self.assertIn(
            (
                "http://snomed.info/sct",
                "27658006",
            ),
            translation_pairs,
        )

    def test_epic_cda_includes_medication_list_items(self):
        bundle = {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": "p1",
                        "name": [{"family": "Muster", "given": ["Max"]}],
                    }
                },
                {
                    "resource": {
                        "resourceType": "Medication",
                        "id": "m1",
                        "code": {"text": "ROACCUTAN Weichkaps 10 mg"},
                    }
                },
                {
                    "resource": {
                        "resourceType": "MedicationStatement",
                        "id": "ms1",
                        "status": "active",
                        "subject": {"reference": "Patient/p1"},
                        "medicationReference": {"reference": "Medication/m1"},
                    }
                },
            ],
        }

        cda_xml = fhir_medications_to_epic_cda(bundle)
        ns = {"hl7": "urn:hl7-org:v3"}
        root = ET.fromstring(cda_xml)

        item = root.find(".//hl7:section/hl7:text/hl7:list/hl7:item", ns)
        self.assertIsNotNone(item)
        self.assertIn("ROACCUTAN Weichkaps 10 mg", item.text)

        code_node = root.find(".//hl7:manufacturedMaterial/hl7:code", ns)
        self.assertIsNotNone(code_node)
        self.assertEqual(code_node.attrib.get("displayName"), "ROACCUTAN Weichkaps 10 mg")

    def test_epic_cda_maps_effective_datetime_dose_route_and_filtered_notes(self):
        bundle = {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": "p1",
                        "name": [{"family": "Muster", "given": ["Max"]}],
                    }
                },
                {
                    "resource": {
                        "resourceType": "Medication",
                        "id": "m1",
                        "identifier": [
                            {
                                "system": "urn:epc:id:sgtin",
                                "value": "7680485780715",
                            }
                        ],
                        "code": {
                            "text": "Ramipril (TRIATEC) 1.25 mg Tablette",
                        },
                    }
                },
                {
                    "resource": {
                        "resourceType": "MedicationStatement",
                        "id": "ms1",
                        "status": "active",
                        "subject": {"reference": "Patient/p1"},
                        "medicationReference": {"reference": "Medication/m1"},
                        "effectiveDateTime": "2025-05-01",
                        "dosage": [
                            {
                                "text": "Einnahme: 1 Tablette (1.25 mg) 1 mal täglich morgens [1-0-0-0]",
                                "doseAndRate": [
                                    {
                                        "doseQuantity": {
                                            "value": 1.25,
                                            "unit": "mg",
                                        }
                                    }
                                ],
                                "route": {
                                    "coding": [
                                        {
                                            "system": "http://snomed.info/sct",
                                            "code": "26643006",
                                            "display": "Oral route",
                                        }
                                    ]
                                },
                            }
                        ],
                        "note": [
                            {"text": "Einnahme: 1 Tablette (1.25 mg) 1 mal täglich morgens [1-0-0-0]"},
                            {"text": "20251222234501+0100"},
                            {"text": "completed"},
                            {"text": "1x täglich morgens nach Zeitplan"},
                        ],
                    }
                },
            ],
        }

        cda_xml = fhir_medications_to_epic_cda(bundle)
        ns = {"hl7": "urn:hl7-org:v3"}
        root = ET.fromstring(cda_xml)

        effective_low = root.find(
            ".//hl7:substanceAdministration/hl7:effectiveTime/hl7:low",
            ns,
        )
        self.assertIsNotNone(effective_low)
        self.assertEqual(effective_low.attrib.get("value"), "20250501")

        dose_quantity = root.find(
            ".//hl7:substanceAdministration/hl7:doseQuantity",
            ns,
        )
        self.assertIsNotNone(dose_quantity)
        self.assertEqual(dose_quantity.attrib.get("value"), "1.25")
        self.assertEqual(dose_quantity.attrib.get("unit"), "mg")

        route_code = root.find(
            ".//hl7:substanceAdministration/hl7:routeCode",
            ns,
        )
        self.assertIsNotNone(route_code)
        self.assertEqual(route_code.attrib.get("code"), "26643006")

        medication_code = root.find(
            ".//hl7:manufacturedMaterial/hl7:code",
            ns,
        )
        self.assertIsNotNone(medication_code)
        self.assertEqual(medication_code.attrib.get("code"), "7680485780715")
        self.assertEqual(medication_code.attrib.get("codeSystem"), "urn:epc:id:sgtin")

        annotation_texts = {
            item.text
            for item in root.findall(
                ".//hl7:substanceAdministration/hl7:entryRelationship/hl7:act/hl7:text",
                ns,
            )
            if item.text
        }
        self.assertIn("1x täglich morgens nach Zeitplan", annotation_texts)
        self.assertNotIn("completed", annotation_texts)
        self.assertNotIn("20251222234501+0100", annotation_texts)

    @patch("services.emediplan_service.requests.get")
    def test_fetch_medication_bundle_from_fhir_server(self, mock_get):
        response = Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "resourceType": "Bundle",
            "type": "searchset",
            "entry": [
                {
                    "resource": {
                        "resourceType": "MedicationStatement",
                        "id": "ms1",
                    }
                }
            ],
        }
        mock_get.return_value = response

        bundle = fetch_medication_bundle_from_fhir_server(
            "http://fhir-server:8080/fhir",
            patient_id="pat-1",
            count=50,
        )

        self.assertEqual(bundle["resourceType"], "Bundle")
        self.assertEqual(bundle["type"], "searchset")

        kwargs = mock_get.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Accept"], "application/fhir+json")

        params = kwargs["params"]
        self.assertIn(("_count", "50"), params)
        self.assertIn(("subject", "Patient/pat-1"), params)

    @patch("services.emediplan_service.requests.post")
    @patch("services.emediplan_service.build_bundle_entry")
    def test_import_emediplan_to_fhir_server(self, mock_build_bundle_entry, mock_post):
        mock_build_bundle_entry.side_effect = lambda resource: {
            "fullUrl": f"urn:uuid:{resource.get('id', 'x')}",
            "resource": resource,
            "request": {
                "method": "POST",
                "url": resource["resourceType"],
            },
        }

        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "resourceType": "Bundle",
            "type": "transaction-response",
        }
        mock_post.return_value = response

        report = import_emediplan_to_fhir_server(
            self._sample_chmed16a_payload(),
            "http://fhir-server:8080/fhir",
        )

        self.assertEqual(report["status"], "imported")
        self.assertEqual(report["fhir_status"], 200)
        self.assertEqual(report["bundle_entry_count"], 3)

        kwargs = mock_post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/fhir+json")
        self.assertEqual(kwargs["json"]["type"], "transaction")

        entries = kwargs["json"]["entry"]
        med_stmt = next(
            item["resource"]
            for item in entries
            if item["resource"].get("resourceType") == "MedicationStatement"
        )

        self.assertTrue(
            med_stmt["subject"]["reference"].startswith("urn:uuid:"),
        )
        self.assertTrue(
            med_stmt["medicationReference"]["reference"].startswith("urn:uuid:"),
        )

    @patch("services.emediplan_service.requests.post")
    @patch("services.emediplan_service.build_bundle_entry")
    def test_import_rewrites_medication_reference_when_medication_id_is_upserted(self, mock_build_bundle_entry, mock_post):
        def build_entry(resource):
            resource_type = resource.get("resourceType")
            resource_id = resource.get("id", "x")

            if resource_type == "Medication":
                # Simulate build_bundle_entry behavior when an existing server
                # resource is found and the ID is replaced for PUT upsert.
                resource["id"] = "server-medication-id-123"

            return {
                "fullUrl": f"urn:uuid:{resource_type}-{resource_id}",
                "resource": resource,
                "request": {
                    "method": "POST",
                    "url": resource_type,
                },
            }

        mock_build_bundle_entry.side_effect = build_entry

        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "resourceType": "Bundle",
            "type": "transaction-response",
        }
        mock_post.return_value = response

        report = import_emediplan_to_fhir_server(
            self._sample_chmed16a_payload(),
            "http://fhir-server:8080/fhir",
        )

        self.assertEqual(report["status"], "imported")

        entries = mock_post.call_args.kwargs["json"]["entry"]

        medication_entry = next(
            item
            for item in entries
            if item["resource"].get("resourceType") == "Medication"
        )
        med_stmt_entry = next(
            item
            for item in entries
            if item["resource"].get("resourceType") == "MedicationStatement"
        )

        self.assertEqual(
            med_stmt_entry["resource"]["medicationReference"]["reference"],
            medication_entry["fullUrl"],
        )

    @patch("services.emediplan_service.requests.post")
    @patch("services.emediplan_service.build_bundle_entry")
    def test_import_bundle_to_fhir_server_from_collection(self, mock_build_bundle_entry, mock_post):
        mock_build_bundle_entry.side_effect = lambda resource: {
            "fullUrl": f"urn:uuid:{resource.get('id', 'x')}",
            "resource": resource,
            "request": {
                "method": "POST",
                "url": resource["resourceType"],
            },
        }

        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "resourceType": "Bundle",
            "type": "transaction-response",
        }
        mock_post.return_value = response

        collection_bundle = {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": "p1",
                    }
                }
            ],
        }

        report = import_bundle_to_fhir_server(
            collection_bundle,
            "http://fhir-server:8080/fhir",
        )

        self.assertEqual(report["status"], "imported")
        self.assertEqual(report["bundle_entry_count"], 1)
        self.assertEqual(mock_post.call_args.kwargs["json"]["type"], "transaction")

    @patch("services.emediplan_service.resolve_medication_identity")
    def test_convert_uses_terminology_display_when_mapping_available(self, mock_resolve):
        mock_resolve.return_value = {
            "id": "7680485780715",
            "id_type": 2,
            "display": "Torem 10, Tabletten",
            "gtin": "7680485780715",
            "product_number": "48578071",
            "dispensing_category": "B",
        }

        bundle = emediplan_to_fhir_bundle(self._sample_chmed16a_payload())
        medication = next(
            entry["resource"]
            for entry in bundle["entry"]
            if entry["resource"].get("resourceType") == "Medication"
        )

        coding = medication["code"]["coding"][0]

        self.assertEqual(coding["system"], "urn:epc:id:sgtin")
        self.assertEqual(coding["code"], "7680485780715")
        self.assertEqual(coding["display"], "Torem 10, Tabletten")
        self.assertEqual(medication["code"]["text"], "Torem 10, Tabletten")
        self.assertEqual(medication["status"], "active")
        self.assertIn(
            {
                "url": "https://emediplan.ch/fhir/StructureDefinition/dispensing-category",
                "valueCode": "B",
            },
            medication["extension"],
        )
        self.assertIn(
            "http://fhir.ch/ig/ch-emed/StructureDefinition/ch-emed-medication",
            medication["meta"]["profile"],
        )

    @patch("services.emediplan_service.resolve_medication_identity")
    def test_convert_adds_snomed_and_source_coding(self, mock_resolve):
        mock_resolve.return_value = {
            "id": "7680485780715",
            "id_type": 2,
            "display": "Torem 10, Tabletten",
            "gtin": "7680485780715",
            "product_number": "48578071",
        }

        med = self._sample_emediplan_object()
        med["Medicaments"][0]["Id"] = "1551274"
        med["Medicaments"][0]["IdType"] = 3
        med["Medicaments"][0]["SnomedCode"] = "27658006"
        med["Medicaments"][0]["SnomedDisplay"] = "Amoxicillin (substance)"

        bundle = emediplan_to_fhir_bundle(
            json.dumps(med).encode("utf-8")
        )

        medication = next(
            entry["resource"]
            for entry in bundle["entry"]
            if entry["resource"].get("resourceType") == "Medication"
        )

        coding = medication["code"]["coding"]

        self.assertIn(
            {
                "system": "urn:epc:id:sgtin",
                "code": "7680485780715",
                "display": "Torem 10, Tabletten",
            },
            coding,
        )

        self.assertIn(
            {
                "system": "https://emediplan.ch/fhir/NamingSystem/pharmacode",
                "code": "1551274",
                "display": "1551274",
            },
            coding,
        )

        self.assertIn(
            {
                "system": "http://snomed.info/sct",
                "code": "27658006",
                "display": "Amoxicillin (substance)",
            },
            coding,
        )

    @patch("services.emediplan_service.resolve_medication_identity")
    def test_convert_populates_ch_emed_medication_fields_when_available(self, mock_resolve):
        mock_resolve.return_value = {
            "id": "971867",
            "id_type": 3,
            "display": "ROACCUTAN Weichkaps 10 mg",
            "gtin": None,
            "product_number": None,
            "form": "Weichkapsel",
            "ingredient": "Isotretinoin",
            "strength": {
                "numerator": {
                    "value": 10,
                    "unit": "mg",
                },
                "denominator": {
                    "value": 1,
                    "unit": "1",
                },
            },
        }

        med = self._sample_emediplan_object()
        med["Medicaments"][0]["Id"] = "971867"
        med["Medicaments"][0]["IdType"] = 3

        bundle = emediplan_to_fhir_bundle(json.dumps(med).encode("utf-8"))

        medication = next(
            entry["resource"]
            for entry in bundle["entry"]
            if entry["resource"].get("resourceType") == "Medication"
        )

        self.assertEqual(medication["status"], "active")
        self.assertIn(
            "http://fhir.ch/ig/ch-emed/StructureDefinition/ch-emed-medication",
            medication["meta"]["profile"],
        )
        self.assertEqual(medication["form"]["text"], "Weichkapsel")
        self.assertEqual(
            medication["ingredient"][0]["itemCodeableConcept"]["text"],
            "Isotretinoin",
        )
        self.assertEqual(
            medication["ingredient"][0]["strength"]["numerator"]["value"],
            10,
        )
        self.assertEqual(
            medication["ingredient"][0]["strength"]["numerator"]["unit"],
            "mg",
        )

    @patch("services.emediplan_service.resolve_medication_identity")
    def test_convert_dedupes_equivalent_medication_statements(self, mock_resolve):
        def resolver(id_type, raw_id):
            if raw_id in {"111", "222"}:
                return {
                    "id": "7680485780715",
                    "id_type": 2,
                    "display": "Torem 10, Tabletten",
                    "gtin": "7680485780715",
                    "product_number": "48578071",
                }

            return {
                "id": raw_id,
                "id_type": id_type,
                "display": None,
                "gtin": None,
                "product_number": None,
            }

        mock_resolve.side_effect = resolver

        med = self._sample_emediplan_object()
        med["Medicaments"] = [
            {
                "Id": "111",
                "IdType": 3,
                "Unit": "STK",
                "TkgRsn": "Bluthochdruck/Wasser",
                "Pos": [
                    {
                        "DtFrom": "2026-07-01",
                        "D": [1, 0, 0, 0],
                    }
                ],
            },
            {
                "Id": "222",
                "IdType": 3,
                "Unit": "STK",
                "TkgRsn": "Bluthochdruck/Wasser",
                "Pos": [
                    {
                        "DtFrom": "2026-07-01",
                        "D": [1, 0, 0, 0],
                    }
                ],
            },
        ]

        bundle = emediplan_to_fhir_bundle(
            json.dumps(med).encode("utf-8")
        )

        medications = [
            entry["resource"]
            for entry in bundle["entry"]
            if entry["resource"].get("resourceType") == "Medication"
        ]
        statements = [
            entry["resource"]
            for entry in bundle["entry"]
            if entry["resource"].get("resourceType") == "MedicationStatement"
        ]

        self.assertEqual(len(medications), 1)
        self.assertEqual(len(statements), 1)
        self.assertEqual(
            statements[0]["medicationReference"]["reference"],
            f"Medication/{medications[0]['id']}",
        )

    def test_convert_maps_medical_data_to_observations_and_conditions(self):
        med = self._sample_emediplan_object()
        med["Patient"]["Med"] = {
            "Meas": [
                {"Type": 1, "Unit": 2, "Val": "53"},
                {"Type": 2, "Unit": 1, "Val": "158"},
            ],
            "Rc": [
                {"Id": 1, "R": [577]},
                {"Id": 3, "R": [612]},
            ],
        }

        bundle = emediplan_to_fhir_bundle(
            json.dumps(med).encode("utf-8")
        )

        patient = next(
            entry["resource"]
            for entry in bundle["entry"]
            if entry["resource"].get("resourceType") == "Patient"
        )
        patient_ref = f"Patient/{patient['id']}"

        observations = [
            entry["resource"]
            for entry in bundle["entry"]
            if entry["resource"].get("resourceType") == "Observation"
        ]

        self.assertEqual(len(observations), 2)

        loinc_codes = {
            obs["code"]["coding"][0]["code"]
            for obs in observations
        }
        self.assertIn("29463-7", loinc_codes)
        self.assertIn("8302-2", loinc_codes)

        for obs in observations:
            self.assertEqual(obs["subject"]["reference"], patient_ref)

        conditions = [
            entry["resource"]
            for entry in bundle["entry"]
            if entry["resource"].get("resourceType") == "Condition"
        ]

        self.assertEqual(len(conditions), 2)

        risk_codes = {
            condition["code"]["coding"][0]["code"]
            for condition in conditions
        }
        self.assertIn("577", risk_codes)
        self.assertIn("612", risk_codes)

        for condition in conditions:
            self.assertEqual(condition["subject"]["reference"], patient_ref)

    def test_convert_maps_official_chmed16a_risk_displays(self):
        med = self._sample_emediplan_object()
        med["Patient"]["Med"] = {
            "DLstMen": "",
            "Meas": [
                {"Type": 1, "Unit": 2, "Val": "53"},
                {"Type": 2, "Unit": 1, "Val": "158"},
            ],
            "Rc": [
                {"Id": 1, "R": [577]},
                {"Id": 2},
                {"Id": 3, "R": [612]},
                {"Id": 4},
                {"Id": 5},
                {"Id": 6, "R": [555, 571]},
            ],
        }

        bundle = emediplan_to_fhir_bundle(
            json.dumps(med).encode("utf-8")
        )

        conditions = [
            entry["resource"]
            for entry in bundle["entry"]
            if entry["resource"].get("resourceType") == "Condition"
        ]

        self.assertEqual(len(conditions), 4)

        risk_display_by_code = {
            condition["code"]["coding"][0]["code"]: condition["code"]["coding"][0]["display"]
            for condition in conditions
        }

        self.assertEqual(
            risk_display_by_code["577"],
            "Renal insufficiency, mild (Clcr >=60-89 ml/min)",
        )
        self.assertEqual(
            risk_display_by_code["612"],
            "Women of childbearing potential",
        )
        self.assertEqual(
            risk_display_by_code["555"],
            "Allergy to penicillins",
        )
        self.assertEqual(
            risk_display_by_code["571"],
            "Allergy to acetylsalicylic acid",
        )


if __name__ == "__main__":
    unittest.main()
