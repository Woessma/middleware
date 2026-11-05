import copy
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock, patch

import requests
from fastapi.testclient import TestClient

from main import app
from services.patient_service import PatientLookupError, PatientMatchConflictError
from services.vacd_import_guard import VacdImportGuard
from services.vacd_send_service import (
    _retain_new_immunizations,
    _same_immunization,
    _search_resources,
    create_or_find_vacd_patient,
    send_vacd_bundle,
)
from tests.test_vacd_send_validation import document, outcome


BASE = "https://target.invalid/fhir"


def patient(patient_id="existing"):
    return {
        "resourceType": "Patient", "id": patient_id,
        "identifier": [{"system": "urn:oid:1.2.3", "value": "synthetic"}],
        "name": [{"family": "Synthetic", "given": ["Test"]}],
        "birthDate": "2000-01-02",
    }


def vaccination(resource_id="old", value="source-1"):
    return {
        "resourceType": "Immunization", "id": resource_id, "status": "completed",
        "identifier": [{"system": "urn:oid:1.2.4", "value": value}],
        "patient": {"reference": "Patient/existing"},
        "occurrenceDateTime": "2020-01-02", "lotNumber": "synthetic-lot",
        "vaccineCode": {"coding": [{"system": "urn:synthetic:vaccine", "code": "TEST"}]},
    }


def response(resources=(), **extra):
    return Mock(status_code=200, json=lambda: {
        "resourceType": "Bundle", "type": "searchset",
        "total": len(resources),
        "entry": [{"resource": resource} for resource in resources], **extra,
    })


def mixed_document():
    bundle = document()
    bundle["entry"][1]["resource"] = patient("patient")
    bundle["entry"][4]["resource"] = vaccination("immunization")
    new = vaccination("new", "source-2")
    new["occurrenceDateTime"] = "2021-01-02"
    bundle["entry"].append({"fullUrl": "urn:uuid:new", "resource": new})
    composition = bundle["entry"][0]["resource"]
    composition["identifier"] = {"system": "urn:oid:1.2.5", "value": "synthetic-document"}
    composition["section"] = [{
        "code": {"coding": [{"system": "http://loinc.org", "code": "11369-6"}]},
        "text": {"status": "generated", "div": '<div xmlns="http://www.w3.org/1999/xhtml">STALE</div>'},
        "entry": [{"reference": "urn:uuid:immunization"}, {"reference": "urn:uuid:new"}],
    }]
    return bundle


class VacdPatientTests(unittest.TestCase):
    def test_exact_identifier_match_searches_all_identifiers_without_creation(self):
        source = patient()
        source["identifier"].append({"system": "urn:oid:1.2.9", "value": "second"})
        with (
            patch("services.vacd_send_service.requests.get", side_effect=[response([patient()]), response([])]) as get,
            patch("services.vacd_send_service.requests.post") as post,
        ):
            found, matched = create_or_find_vacd_patient(source, BASE)
        self.assertTrue(matched)
        self.assertEqual(found["id"], "existing")
        self.assertEqual(get.call_count, 2)
        post.assert_not_called()

    def test_conflicting_identifiers_or_multiple_matches_block(self):
        other = patient("other")
        other["identifier"] = [{"system": "urn:oid:1.2.9", "value": "second"}]
        source = patient()
        source["identifier"].extend(other["identifier"])
        for responses in ([response([patient(), patient("other")])], [response([patient()]), response([other])]):
            with (
                self.subTest(responses=responses),
                patch("services.vacd_send_service.requests.get", side_effect=responses),
                patch("services.vacd_send_service.requests.post") as post,
            ):
                with self.assertRaises(PatientMatchConflictError):
                    create_or_find_vacd_patient(source, BASE)
                post.assert_not_called()

    def test_unsupported_identifier_uses_exact_full_name_and_birthdate(self):
        unsupported = Mock(status_code=400, json=lambda: {
            "resourceType": "OperationOutcome", "issue": [{"code": "not-supported"}],
        })
        wrong_name = patient("wrong")
        wrong_name["name"][0]["given"] = ["SomeoneElse"]
        with (
            patch("services.vacd_send_service.requests.get", side_effect=[
                unsupported, response([wrong_name, patient()]),
            ]),
            patch("services.vacd_send_service.requests.post") as post,
        ):
            found, matched = create_or_find_vacd_patient(patient(), BASE)
        self.assertTrue(matched)
        self.assertEqual(found["id"], "existing")
        post.assert_not_called()

    def test_no_match_creates_patient_without_local_id(self):
        created = Mock(status_code=201, json=lambda: patient("new"))
        with (
            patch("services.vacd_send_service.requests.get", return_value=response()),
            patch("services.vacd_send_service.requests.post", return_value=created) as post,
        ):
            found, matched = create_or_find_vacd_patient(patient(), BASE)
        self.assertFalse(matched)
        self.assertEqual(found["id"], "new")
        self.assertNotIn("id", post.call_args.kwargs["json"])

    def test_ignored_identifier_filter_blocks_creation(self):
        unrelated = patient()
        unrelated["identifier"][0]["value"] = "different"
        with (
            patch("services.vacd_send_service.requests.get", return_value=response([unrelated])),
            patch("services.vacd_send_service.requests.post") as post,
        ):
            with self.assertRaises(PatientLookupError):
                create_or_find_vacd_patient(patient(), BASE)
            post.assert_not_called()

    def test_identifier_match_with_conflicting_birthdate_or_other_identifier_blocks(self):
        for field in ("birthDate", "identifier"):
            candidate = patient()
            source = patient()
            if field == "birthDate":
                candidate["birthDate"] = "2001-01-02"
            else:
                source["identifier"].append({"system": "urn:oid:1.2.9", "value": "source"})
                candidate["identifier"].append({"system": "urn:oid:1.2.9", "value": "different"})
            with (
                self.subTest(field=field),
                patch("services.vacd_send_service.requests.get", return_value=response([candidate])),
                patch("services.vacd_send_service.requests.post") as post,
            ):
                with self.assertRaises(PatientMatchConflictError):
                    create_or_find_vacd_patient(source, BASE)
                post.assert_not_called()

    def test_missing_safe_identity_and_demographic_conflicts_block(self):
        source = patient()
        source.pop("identifier")
        for candidates in ([patient(), patient("other")],):
            with (
                patch("services.vacd_send_service.requests.get", return_value=response(candidates)),
                patch("services.vacd_send_service.requests.post") as post,
            ):
                with self.assertRaises(PatientMatchConflictError):
                    create_or_find_vacd_patient(source, BASE)
                post.assert_not_called()
        with self.assertRaises(PatientMatchConflictError):
            create_or_find_vacd_patient({"resourceType": "Patient"}, BASE)

    def test_malformed_incomplete_or_warning_searches_are_not_no_match(self):
        for bundle in (
            {"resourceType": "OperationOutcome"},
            {"resourceType": "Bundle", "type": "searchset", "total": 1},
            {"resourceType": "Bundle", "type": "searchset", "entry": [{
                "resource": {"resourceType": "OperationOutcome", "issue": [{"severity": "warning"}]},
            }]},
        ):
            with self.subTest(bundle=bundle), self.assertRaises(PatientLookupError):
                _search_resources(bundle, "Patient")
        with self.assertRaises(PatientMatchConflictError):
            _search_resources({
                "resourceType": "Bundle", "type": "searchset",
                "link": [{"relation": "next", "url": BASE + "/Patient?page=2"}],
            }, "Patient")


class VacdDuplicateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = directory.name + "/imports.db"
        patcher = patch("services.vacd_send_service.VACD_IMPORT_DB", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_mixed_document_is_rebuilt_and_final_payload_validated(self):
        bundle = mixed_document()
        original = copy.deepcopy(bundle)
        validated = []

        def validate(payload):
            validated.append(copy.deepcopy(payload))
            return 200, outcome("warning")

        with (
            patch("services.vacd_send_service.validate_fhir_bundle", side_effect=validate),
            patch("services.vacd_send_service.create_or_find_vacd_patient", return_value=(patient(), True)),
            patch("services.vacd_send_service.requests.get", return_value=response([vaccination()])),
            patch("services.vacd_send_service.requests.post", return_value=Mock(
                status_code=201, json=lambda: {"resourceType": "Bundle"},
            )) as post,
        ):
            report = send_vacd_bundle(bundle, BASE)
        self.assertEqual(report["status"], "sent")
        self.assertEqual(report["immunizations"], {"new": 1, "skipped": 1})
        outbound = post.call_args.kwargs["json"]
        self.assertEqual(outbound, validated[1])
        self.assertEqual(bundle, original)
        vaccines = [e["resource"] for e in outbound["entry"] if e["resource"]["resourceType"] == "Immunization"]
        self.assertEqual([r["id"] for r in vaccines], ["new"])
        section = outbound["entry"][0]["resource"]["section"][0]
        self.assertEqual(section["entry"], [{"reference": "Immunization/new"}])
        self.assertNotIn("STALE", section["text"]["div"])
        self.assertIn("2021-01-02", section["text"]["div"])
        self.assertNotIn("2020-01-02", section["text"]["div"])
        self.assertEqual(outbound["entry"][0]["resource"]["relatesTo"][0]["code"], "transforms")

    def test_all_duplicates_or_repeated_document_never_post(self):
        bundle = mixed_document()
        resources = [entry["resource"] for entry in bundle["entry"] if entry["resource"]["resourceType"] == "Immunization"]
        with (
            patch("services.vacd_send_service.validate_fhir_bundle", return_value=(200, outcome("information"))),
            patch("services.vacd_send_service.create_or_find_vacd_patient", return_value=(patient(), True)) as find,
            patch("services.vacd_send_service.requests.get", return_value=response(resources)),
            patch("services.vacd_send_service.requests.post") as post,
        ):
            first = send_vacd_bundle(bundle, BASE)
            second = send_vacd_bundle(bundle, BASE)
        self.assertEqual(first["reason"], "no-new-immunizations")
        self.assertEqual(second["reason"], "document-already-processed")
        self.assertEqual(first["immunizations"]["skipped"], 2)
        find.assert_called_once()
        post.assert_not_called()

    def test_reference_rewriting_precedes_comparison_of_clinical_extensions(self):
        bundle = mixed_document()
        bundle["entry"][4]["resource"]["extension"] = [{
            "url": "urn:synthetic:patient-reference",
            "valueReference": {"reference": "urn:uuid:patient"},
        }]
        previous = vaccination()
        previous["extension"] = [{
            "url": "urn:synthetic:patient-reference",
            "valueReference": {"reference": BASE + "/Patient/existing"},
        }]
        with (
            patch("services.vacd_send_service.validate_fhir_bundle", return_value=(200, outcome("information"))),
            patch("services.vacd_send_service.create_or_find_vacd_patient", return_value=(patient(), True)),
            patch("services.vacd_send_service.requests.get", return_value=response([previous])),
            patch("services.vacd_send_service.requests.post", return_value=Mock(
                status_code=201, json=lambda: {"resourceType": "Bundle"},
            )),
        ):
            report = send_vacd_bundle(bundle, BASE)
        self.assertEqual(report["status"], "sent")
        self.assertEqual(report["immunizations"], {"new": 1, "skipped": 1})

    def test_same_document_identity_changed_content_blocks(self):
        with VacdImportGuard(self.path, BASE, "key", "hash") as guard:
            guard.record("completed")
        with self.assertRaises(PatientMatchConflictError):
            with VacdImportGuard(self.path, BASE, "key", "changed"):
                self.fail("Changed source must not enter")

    def test_completed_source_hash_matches_legacy_generated_document_key(self):
        with VacdImportGuard(self.path, BASE, "generated-old-uuid", "same-source") as guard:
            guard.record("completed")
        with VacdImportGuard(self.path, BASE, "generated-new-uuid", "same-source") as guard:
            self.assertTrue(guard.completed)
        with VacdImportGuard(self.path, BASE + "/other", "generated-new-uuid", "same-source") as guard:
            self.assertFalse(guard.completed)

    def test_source_identifier_and_hash_survive_generated_vacd_identity(self):
        source_id = {"system": "urn:synthetic:cda", "value": "source"}
        first = mixed_document()
        second = copy.deepcopy(first)
        second["entry"][0]["resource"]["identifier"]["value"] = "regenerated"
        with (
            patch("services.vacd_send_service.validate_fhir_bundle", return_value=(200, outcome("information"))),
            patch("services.vacd_send_service.create_or_find_vacd_patient", return_value=(patient(), True)) as find,
            patch("services.vacd_send_service.requests.get", return_value=response()),
            patch("services.vacd_send_service.requests.post", return_value=Mock(
                status_code=201, json=lambda: {"resourceType": "Bundle"},
            )) as post,
        ):
            self.assertEqual(send_vacd_bundle(
                first, BASE, source_document_hash="same-source",
                source_document_identifier=source_id,
            )["status"], "sent")
            self.assertEqual(send_vacd_bundle(
                second, BASE, source_document_hash="same-source",
                source_document_identifier=source_id,
            )["reason"], "document-already-processed")
            with self.assertRaises(PatientMatchConflictError):
                send_vacd_bundle(
                    second, BASE, source_document_hash="changed-source",
                    source_document_identifier=source_id,
                )
        find.assert_called_once()
        post.assert_called_once()

    def test_uncertain_write_survives_reopen(self):
        with VacdImportGuard(self.path, BASE, "key", "hash") as guard:
            guard.record("pending-bundle")
        with self.assertRaises(PatientMatchConflictError):
            with VacdImportGuard(self.path, BASE, "key", "hash"):
                self.fail("Uncertain write must not be retried")
        with self.assertRaises(PatientMatchConflictError):
            with VacdImportGuard(self.path, BASE, "other-document", "other-hash"):
                self.fail("Another document must not race an uncertain previous write")

    def test_destination_lock_serializes_parallel_imports(self):
        acquired = Event()
        attempted = Event()
        release = Event()

        def first():
            with VacdImportGuard(self.path, BASE, "key", "hash") as guard:
                acquired.set()
                if not release.wait(5):
                    raise AssertionError("Test release timed out")
                guard.record("completed")

        def second():
            attempted.set()
            with VacdImportGuard(self.path, BASE, "key", "hash") as guard:
                return guard.completed

        with ThreadPoolExecutor(max_workers=2) as pool:
            initial = pool.submit(first)
            self.assertTrue(acquired.wait(5))
            following = pool.submit(second)
            try:
                self.assertTrue(attempted.wait(5))
                self.assertFalse(following.done())
            finally:
                release.set()
            initial.result(timeout=5)
            self.assertTrue(following.result(timeout=5))

    def test_failed_final_validation_does_not_record_an_uncertain_write(self):
        from services.vacd_send_service import VacdValidationRejected

        with (
            patch("services.vacd_send_service.validate_fhir_bundle", side_effect=[
                (200, outcome("information")), (200, outcome("error")),
            ]),
            patch("services.vacd_send_service.create_or_find_vacd_patient", return_value=(patient(), True)),
            patch("services.vacd_send_service.requests.get", return_value=response()),
            patch("services.vacd_send_service.requests.post") as post,
        ):
            with self.assertRaises(VacdValidationRejected):
                send_vacd_bundle(mixed_document(), BASE)
        post.assert_not_called()
        with VacdImportGuard(self.path, BASE, "other", "other") as guard:
            self.assertFalse(guard.completed)

    def test_destination_error_outcome_is_not_marked_completed_even_with_http_200(self):
        with (
            patch("services.vacd_send_service.validate_fhir_bundle", return_value=(200, outcome("information"))),
            patch("services.vacd_send_service.create_or_find_vacd_patient", return_value=(patient(), True)),
            patch("services.vacd_send_service.requests.get", return_value=response()),
            patch("services.vacd_send_service.requests.post", return_value=Mock(
                status_code=200, json=lambda: outcome("error"),
            )),
        ):
            report = send_vacd_bundle(mixed_document(), BASE)
        self.assertEqual(report["status"], "partial-error")

    def test_a_later_conflicting_identifier_match_is_not_hidden_by_an_exact_match(self):
        conflict = vaccination()
        conflict["doseQuantity"] = {"value": 2}
        with self.assertRaises(PatientMatchConflictError):
            _retain_new_immunizations(mixed_document(), [vaccination(), conflict])

    def test_timeout_blocks_automatic_retry(self):
        bundle = mixed_document()
        with (
            patch("services.vacd_send_service.validate_fhir_bundle", return_value=(200, outcome("information"))),
            patch("services.vacd_send_service.create_or_find_vacd_patient", return_value=(patient(), True)),
            patch("services.vacd_send_service.requests.get", return_value=response()),
            patch("services.vacd_send_service.requests.post", side_effect=requests.Timeout("Synthetic timeout")) as post,
        ):
            self.assertEqual(send_vacd_bundle(bundle, BASE)["status"], "partial-error")
            with self.assertRaises(PatientMatchConflictError):
                send_vacd_bundle(bundle, BASE)
        post.assert_called_once()

    def test_uncertain_patient_creation_blocks_retry_before_another_write(self):
        with (
            patch("services.vacd_send_service.validate_fhir_bundle", return_value=(200, outcome("information"))),
            patch("services.vacd_send_service.requests.get", return_value=response()),
            patch("services.vacd_send_service.requests.post", side_effect=requests.Timeout("Synthetic timeout")) as post,
        ):
            with self.assertRaises(requests.Timeout):
                send_vacd_bundle(mixed_document(), BASE)
            with self.assertRaises(PatientMatchConflictError):
                send_vacd_bundle(mixed_document(), BASE)
        post.assert_called_once()

    def test_read_failure_allows_safe_retry(self):
        with (
            patch("services.vacd_send_service.validate_fhir_bundle", return_value=(200, outcome("information"))),
            patch("services.vacd_send_service.requests.get", side_effect=requests.Timeout("Synthetic read timeout")),
            patch("services.vacd_send_service.requests.post") as post,
        ):
            for _ in range(2):
                with self.assertRaises(requests.Timeout):
                    send_vacd_bundle(mixed_document(), BASE)
        post.assert_not_called()

    def test_non_fhir_or_async_destination_response_is_not_success(self):
        for status, payload in ((200, "not-fhir"), (202, {"resourceType": "Bundle"})):
            with (
                self.subTest(status=status),
                patch("services.vacd_send_service.validate_fhir_bundle", return_value=(200, outcome("information"))),
                patch("services.vacd_send_service.create_or_find_vacd_patient", return_value=(patient(), True)),
                patch("services.vacd_send_service.requests.get", return_value=response()),
                patch("services.vacd_send_service.requests.post", return_value=Mock(
                    status_code=status, json=lambda: payload,
                )),
            ):
                report = send_vacd_bundle(mixed_document(), BASE + f"/case-{status}")
                self.assertEqual(report["status"], "partial-error")

    def test_same_identifier_changed_dose_blocks(self):
        changed = vaccination()
        changed["doseQuantity"] = {"value": 2, "unit": "mL"}
        with self.assertRaisesRegex(PatientMatchConflictError, "field: doseQuantity"):
            _same_immunization(changed, vaccination())

    def test_clinical_match_requires_date_code_and_lot(self):
        other_id = vaccination(value="other-source")
        self.assertTrue(_same_immunization(other_id, vaccination()))
        other_id.pop("identifier")
        existing = vaccination()
        existing.pop("identifier")
        self.assertTrue(_same_immunization(other_id, existing))
        other_id.pop("lotNumber")
        with self.assertRaises(PatientMatchConflictError):
            _same_immunization(other_id, existing)

    def test_incoming_duplicates_are_removed_and_narrative_escaped(self):
        bundle = mixed_document()
        new = bundle["entry"][-1]
        new["resource"]["vaccineCode"]["text"] = "<script>Synthetic</script>"
        duplicate = copy.deepcopy(new)
        duplicate["resource"]["id"] = "duplicate"
        duplicate["fullUrl"] = "urn:uuid:duplicate"
        bundle["entry"].append(duplicate)
        bundle["entry"][0]["resource"]["section"][0]["entry"].append({"reference": "urn:uuid:duplicate"})
        self.assertEqual(_retain_new_immunizations(bundle, []), (2, 1))
        text = bundle["entry"][0]["resource"]["section"][0]["text"]["div"]
        self.assertIn("&lt;script&gt;", text)
        self.assertNotIn("<script>", text)

    def test_endpoint_conflict_and_lookup_errors_are_explicit(self):
        for error, status in (
            (PatientMatchConflictError("Synthetic ambiguity"), 409),
            (PatientLookupError("Synthetic lookup failure"), 502),
        ):
            with (
                patch("main.cda_to_fhir_bundle", return_value=document()),
                patch("main._embed_precreated_resource"),
                patch("main._validate_bundle", side_effect=lambda bundle: bundle),
                patch("main.send_vacd_bundle", side_effect=error),
            ):
                result = TestClient(app).post("/cda/vacd/send", content=b"<ClinicalDocument/>")
            self.assertEqual(result.status_code, status)
            self.assertEqual(result.json()["resourceType"], "OperationOutcome")
