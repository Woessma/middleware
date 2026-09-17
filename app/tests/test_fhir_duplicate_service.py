import unittest
from unittest.mock import Mock, patch

from services.fhir_duplicate_service import find_exact_fhir_duplicates


class FhirDuplicateServiceTests(unittest.TestCase):
    @patch("services.fhir_duplicate_service.requests.get")
    def test_finds_exact_duplicate_medication_statements(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "MedicationStatement",
                        "id": "ms-1",
                        "status": "active",
                        "subject": {"reference": "Patient/3402"},
                        "medicationReference": {"reference": "Medication/3411"},
                        "effectivePeriod": {"start": "2016-02-10"},
                        "reasonCode": [{"text": "Bluthochdruck/Wasser"}],
                        "dosage": [{"text": "Morgen: 1, Mittag: 0, Abend: 0, Nacht: 0"}],
                        "meta": {"versionId": "1"},
                    }
                },
                {
                    "resource": {
                        "resourceType": "MedicationStatement",
                        "id": "ms-2",
                        "status": "active",
                        "subject": {"reference": "Patient/3402"},
                        "medicationReference": {"reference": "Medication/3411"},
                        "effectivePeriod": {"start": "2016-02-10"},
                        "reasonCode": [{"text": "Bluthochdruck/Wasser"}],
                        "dosage": [{"text": "Morgen: 1, Mittag: 0, Abend: 0, Nacht: 0"}],
                        "meta": {"versionId": "2"},
                    }
                },
                {
                    "resource": {
                        "resourceType": "MedicationStatement",
                        "id": "ms-3",
                        "status": "active",
                        "subject": {"reference": "Patient/3402"},
                        "medicationReference": {"reference": "Medication/3413"},
                        "effectivePeriod": {"start": "2016-02-10"},
                        "reasonCode": [{"text": "Bluthochdruck/Wasser"}],
                        "dosage": [{"text": "Morgen: 1, Mittag: 0, Abend: 0, Nacht: 0"}],
                    }
                },
            ],
        }
        mock_get.return_value = response

        result = find_exact_fhir_duplicates(
            resource_type="MedicationStatement",
            patient_id="3402",
            fhir_base="http://fhir-server:8080/fhir",
            count=100,
        )

        self.assertEqual(result["resourceType"], "MedicationStatement")
        self.assertEqual(result["count"], 3)
        self.assertEqual(len(result["duplicateGroups"]), 1)
        self.assertEqual(result["duplicateGroups"][0]["count"], 2)
        self.assertEqual(result["duplicateGroups"][0]["ids"], ["ms-1", "ms-2"])


if __name__ == "__main__":
    unittest.main()