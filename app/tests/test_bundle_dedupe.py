import unittest

from main import _stabilize_bundle
from services.cda_bundle_service import _dedupe_bundle_entries


class BundleDedupeTests(unittest.TestCase):
    def test_dedupe_keeps_distinct_post_entries_with_same_url(self):
        entries = [
            {
                "resource": {
                    "resourceType": "Encounter",
                    "identifier": [
                        {"system": "urn:oid:1.2.3", "value": "enc-1"}
                    ],
                },
                "request": {"method": "POST", "url": "Encounter"},
            },
            {
                "resource": {
                    "resourceType": "Encounter",
                    "identifier": [
                        {"system": "urn:oid:1.2.3", "value": "enc-2"}
                    ],
                },
                "request": {"method": "POST", "url": "Encounter"},
            },
        ]

        deduped = _dedupe_bundle_entries(entries)

        self.assertEqual(len(deduped), 2)

    def test_dedupe_removes_true_duplicate_post_entries(self):
        entry = {
            "resource": {
                "resourceType": "Observation",
                "identifier": [
                    {
                        "system": "https://woess.ch/fhir/NamingSystem/cda-import-observation",
                        "value": "same",
                    }
                ],
                "valueString": "ABC",
            },
            "request": {"method": "POST", "url": "Observation"},
        }

        deduped = _dedupe_bundle_entries([entry, entry])

        self.assertEqual(len(deduped), 1)

    def test_dedupe_removes_true_duplicate_put_entries(self):
        entries = [
            {
                "resource": {"resourceType": "Patient", "id": "1"},
                "request": {"method": "PUT", "url": "Patient/1"},
            },
            {
                "resource": {"resourceType": "Patient", "id": "1"},
                "request": {"method": "PUT", "url": "Patient/1"},
            },
        ]

        deduped = _dedupe_bundle_entries(entries)

        self.assertEqual(len(deduped), 1)

    def test_dedupe_removes_same_business_identity_even_when_post_url_differs(self):
        entries = [
            {
                "resource": {
                    "resourceType": "Observation",
                    "identifier": [
                        {"system": "https://woess.ch/fhir/NamingSystem/cda-import-observation", "value": "same"}
                    ],
                    "valueString": "ABC",
                },
                "request": {"method": "POST", "url": "Observation"},
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "identifier": [
                        {"system": "https://woess.ch/fhir/NamingSystem/cda-import-observation", "value": "same"}
                    ],
                    "valueString": "ABC",
                },
                "request": {"method": "POST", "url": "Observation/duplicate"},
            },
        ]

        deduped = _dedupe_bundle_entries(entries)

        self.assertEqual(len(deduped), 1)

    def test_stabilize_bundle_removes_duplicates_and_sets_if_none_exist(self):
        bundle = {
            "resourceType": "Bundle",
            "type": "transaction",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Observation",
                        "identifier": [
                            {
                                "system": "https://woess.ch/fhir/NamingSystem/cda-import-observation",
                                "value": "same",
                            }
                        ],
                        "status": "final",
                    },
                    "request": {"method": "POST", "url": "Observation"},
                },
                {
                    "resource": {
                        "resourceType": "Observation",
                        "identifier": [
                            {
                                "system": "https://woess.ch/fhir/NamingSystem/cda-import-observation",
                                "value": "same",
                            }
                        ],
                        "status": "final",
                    },
                    "request": {"method": "POST", "url": "Observation/duplicate"},
                },
            ],
        }

        stabilized = _stabilize_bundle(bundle)

        self.assertEqual(len(stabilized["entry"]), 1)
        self.assertEqual(
            stabilized["entry"][0]["request"]["ifNoneExist"],
            "identifier=https://woess.ch/fhir/NamingSystem/cda-import-observation|same",
        )

    def test_stabilize_wraps_single_resource_as_idempotent_transaction(self):
        stabilized = _stabilize_bundle(
            {"resourceType": "MedicationStatement", "id": "med-1"}
        )

        self.assertEqual(stabilized["resourceType"], "Bundle")
        self.assertEqual(stabilized["type"], "transaction")
        self.assertEqual(stabilized["entry"][0]["request"]["method"], "PUT")
        self.assertEqual(
            stabilized["entry"][0]["request"]["url"],
            "MedicationStatement/med-1",
        )

    def test_stabilize_converts_document_bundle_to_transaction(self):
        stabilized = _stabilize_bundle(
            {
                "resourceType": "Bundle",
                "type": "document",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Patient",
                            "id": "patient-1",
                        }
                    }
                ],
            }
        )

        self.assertEqual(stabilized["type"], "transaction")
        self.assertEqual(
            stabilized["entry"][0]["request"],
            {"method": "PUT", "url": "Patient/patient-1"},
        )
