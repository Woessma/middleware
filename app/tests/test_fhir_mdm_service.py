import unittest
from unittest.mock import Mock, patch

from services.fhir_mdm_service import (
    FhirMdmLookupError,
    FhirMdmMatchConflictError,
    MATCH_GRADE_URL,
    MDM_RECORD_STATUS_SYSTEM,
    find_mdm_match,
    find_mdm_matches,
    make_mdm_same_patient_matcher,
    reconcile_mdm_resources,
)


def match_bundle(resource, grade="certain"):
    return {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": resource,
                "search": {
                    "extension": [
                        {"url": MATCH_GRADE_URL, "valueCode": grade},
                    ],
                },
            },
        ],
    }


def golden_patient(patient_id):
    return {
        "resourceType": "Patient",
        "id": patient_id,
        "meta": {"tag": [{"system": MDM_RECORD_STATUS_SYSTEM, "code": "GOLDEN_RECORD"}]},
    }


def match_link(source_id, golden_id):
    return {
        "name": "link",
        "part": [
            {"name": "sourceResourceId", "valueString": f"Patient/{source_id}"},
            {"name": "goldenResourceId", "valueString": f"Patient/{golden_id}"},
            {"name": "matchResult", "valueString": "MATCH"},
        ],
    }


class FhirMdmServiceTests(unittest.TestCase):
    @patch("services.fhir_mdm_service.requests.post")
    def test_patient_uses_server_level_mdm_match_and_returns_certain_match(self, post):
        response = Mock()
        response.json.return_value = match_bundle(golden_patient("golden-1"))
        post.return_value = response

        match = find_mdm_match({"resourceType": "Patient", "name": [{"family": "Test"}]})

        self.assertEqual(match["id"], "golden-1")
        self.assertEqual(
            post.call_args.args[0],
            "http://fhir-server:8080/fhir/$mdm-match",
        )
        self.assertEqual(
            post.call_args.kwargs["json"]["parameter"],
            [
                {
                    "name": "resource",
                    "resource": {
                        "resourceType": "Patient",
                        "name": [{"family": "Test"}],
                    },
                },
                {"name": "resourceType", "valueString": "Patient"},
            ],
        )

    @patch("services.fhir_mdm_service.requests.get")
    @patch("services.fhir_mdm_service.find_mdm_matches")
    def test_source_and_golden_hits_are_one_only_when_confirmed_link_agrees(self, matches, get):
        source = {"resourceType": "Patient", "id": "source-1"}
        golden = golden_patient("golden-1")
        matches.return_value = [
            {"resource": hit, "grade": "certain"} for hit in (source, golden)
        ]
        get.return_value.json.return_value = {
            "resourceType": "Parameters",
            "parameter": [match_link("source-1", "golden-1")],
        }
        self.assertEqual(find_mdm_match({"resourceType": "Patient"}), golden)
        self.assertEqual(get.call_args.kwargs["params"]["resourceId"], "Patient/source-1")
        self.assertEqual(get.call_args.kwargs["params"]["matchResult"], "MATCH")

        for links in ([match_link("source-1", "golden-2")], []):
            with self.subTest(links=links):
                get.return_value.json.return_value["parameter"] = links
                with self.assertRaises(FhirMdmMatchConflictError):
                    find_mdm_match({"resourceType": "Patient"})

    @patch("services.fhir_mdm_service.requests.get")
    @patch("services.fhir_mdm_service.find_mdm_matches")
    def test_source_only_hit_loads_its_golden_resource(self, matches, get):
        source = {"resourceType": "Patient", "id": "source-1"}
        golden = golden_patient("golden-1")
        matches.return_value = [{"resource": source, "grade": "certain"}]
        get.side_effect = [
            Mock(**{"json.return_value": {
                "resourceType": "Parameters",
                "parameter": [match_link("source-1", "golden-1")],
            }}),
            Mock(**{"json.return_value": golden}),
        ]
        self.assertEqual(find_mdm_match({"resourceType": "Patient"}), golden)
        self.assertTrue(get.call_args.args[0].endswith("/Patient/golden-1"))

    @patch("services.fhir_mdm_service.requests.post")
    def test_non_patient_uses_server_level_mdm_match(self, post):
        response = Mock()
        response.json.return_value = match_bundle(
            {"resourceType": "Organization", "id": "golden-org"}
        )
        post.return_value = response

        matches = find_mdm_matches({"resourceType": "Organization", "name": "Clinic"})

        self.assertEqual(matches[0]["resource"]["id"], "golden-org")
        self.assertEqual(
            post.call_args.args[0],
            "http://fhir-server:8080/fhir/$mdm-match",
        )
        self.assertEqual(
            post.call_args.kwargs["json"]["parameter"][1],
            {"name": "resourceType", "valueString": "Organization"},
        )

    @patch("services.fhir_mdm_service.requests.post")
    def test_possible_match_is_a_conflict(self, post):
        response = Mock()
        response.json.return_value = match_bundle(
            {"resourceType": "Practitioner", "id": "practitioner-1"},
            grade="probable",
        )
        post.return_value = response

        with self.assertRaises(FhirMdmMatchConflictError):
            find_mdm_match({"resourceType": "Practitioner"})

    @patch("services.fhir_mdm_service.requests.post")
    def test_invalid_match_response_fails_closed(self, post):
        response = Mock()
        response.json.return_value = {
            "resourceType": "Bundle",
            "entry": [
                {"resource": {"resourceType": "Patient", "id": "p1"}, "search": {}},
            ],
        }
        post.return_value = response

        with self.assertRaises(FhirMdmLookupError):
            find_mdm_match({"resourceType": "Patient"})

    @patch("services.fhir_mdm_service.find_mdm_match")
    def test_reconcile_removes_matched_entries_and_rewrites_references(self, find_match):
        find_match.return_value = {"resourceType": "Patient", "id": "golden-1"}
        patient_entry = {
            "fullUrl": "urn:uuid:source-patient",
            "resource": {"resourceType": "Patient", "id": "source-patient"},
        }
        observation_entry = {
            "resource": {
                "resourceType": "Observation",
                "subject": {"reference": "urn:uuid:source-patient"},
            },
        }
        bundle = {
            "resourceType": "Bundle",
            "entry": [patient_entry, observation_entry],
        }

        reference_map = reconcile_mdm_resources(bundle)

        self.assertEqual(reference_map["Patient/source-patient"], "Patient/golden-1")
        self.assertEqual(reference_map["urn:uuid:source-patient"], "Patient/golden-1")
        self.assertEqual(bundle["entry"], [observation_entry])
        self.assertEqual(
            observation_entry["resource"]["subject"]["reference"],
            "Patient/golden-1",
        )


class MdmSamePatientMatcherTests(unittest.TestCase):
    @patch("services.fhir_mdm_service.find_linked_golden_id")
    def test_matches_only_the_linked_golden_record_and_caches_lookups(self, linked):
        linked.side_effect = lambda _type, source_id: (
            "golden-1" if source_id == "source-1" else None
        )
        matcher = make_mdm_same_patient_matcher()

        self.assertTrue(matcher("Patient/source-1", "Patient/golden-1"))
        self.assertTrue(matcher("Patient/source-1", "Patient/golden-1"))
        self.assertFalse(matcher("Patient/source-1", "Patient/other"))
        self.assertFalse(matcher("Patient/unlinked", "Patient/golden-1"))
        self.assertEqual(linked.call_count, 2)

    @patch("services.fhir_mdm_service.find_linked_golden_id")
    def test_rejects_invalid_source_references_without_lookup(self, linked):
        matcher = make_mdm_same_patient_matcher()

        self.assertFalse(matcher("Observation/1", "Patient/golden-1"))
        self.assertFalse(matcher("Patient/bad id", "Patient/golden-1"))
        linked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
