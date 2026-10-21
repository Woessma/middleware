import unittest
from unittest.mock import Mock, patch

from fhir.bundle import build_bundle_entry


class BundleEntryTests(unittest.TestCase):
    @patch("fhir.bundle.requests.get")
    def test_shared_identifier_matches_after_hapi_omits_null_fields(self, mock_get):
        resource = {
            "resourceType": "Procedure",
            "identifier": [{"system": "urn:test", "value": "same-procedure"}],
            "subject": {"reference": "Patient/p1"},
            "code": {"coding": [{"system": "urn:test", "code": "123", "display": None}]},
            "performer": [{"actor": {"display": "Synthetic author"}}],
        }
        stored_code = {"coding": [{"system": "urn:test", "code": "123"}]}
        response = Mock()
        response.json.return_value = {"entry": [
            {"resource": {**resource, "id": "other-author", "code": stored_code,
                          "performer": [{"actor": {"display": "Different author"}}]}},
            {"resource": {**resource, "id": "same-procedure", "code": stored_code}},
        ]}
        mock_get.return_value = response

        entry = build_bundle_entry(resource)

        self.assertEqual(entry["request"]["url"], "Procedure/same-procedure")

    @patch("fhir.bundle.requests.get")
    def test_shared_identifier_selects_matching_clinical_resource(self, mock_get):
        identifier = {
            "system": "https://fhir.omnilink.ch/fhir/NamingSystem/cda-import-social-history",
            "value": "same-answer",
        }
        resource = {
            "resourceType": "Observation",
            "identifier": [identifier],
            "subject": {"reference": "Patient/p1"},
            "code": {"text": "Question B"},
            "valueString": "Same answer",
        }
        response = Mock()
        response.json.return_value = {"entry": [
            {"resource": {**resource, "id": "question-a", "code": {"text": "Question A"}}},
            {"resource": {**resource, "id": "question-b"}},
        ]}
        mock_get.return_value = response

        entry = build_bundle_entry(resource)

        self.assertEqual(entry["request"]["url"], "Observation/question-b")

    @patch("fhir.bundle.requests.get")
    def test_ambiguous_identifier_never_overwrites_different_clinical_resources(self, mock_get):
        resource = {
            "resourceType": "Observation",
            "identifier": [{"system": "urn:test", "value": "collision"}],
            "subject": {"reference": "Patient/p1"},
            "code": {"text": "New question"},
        }
        response = Mock()
        response.json.return_value = {"entry": [
            {"resource": {**resource, "id": "a", "code": {"text": "Question A"}}},
            {"resource": {**resource, "id": "b", "code": {"text": "Question B"}}},
        ]}
        mock_get.return_value = response

        with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
            build_bundle_entry(resource)

    @patch("fhir.bundle.requests.get")
    def test_cda_identifier_lookup_includes_legacy_namespace(self, mock_get):
        response = Mock()
        response.json.return_value = {"entry": [{"resource": {"id": "legacy-condition"}}]}
        mock_get.return_value = response
        resource = {
            "resourceType": "Condition",
            "identifier": [{
                "system": "https://fhir.omnilink.ch/fhir/NamingSystem/cda-import-condition",
                "value": "same-source",
            }],
        }

        entry = build_bundle_entry(resource)

        self.assertEqual(entry["request"]["url"], "Condition/legacy-condition")
        self.assertEqual(mock_get.call_args.kwargs["params"]["identifier"], (
            "https://fhir.omnilink.ch/fhir/NamingSystem/cda-import-condition|same-source,"
            "https://woess.ch/fhir/NamingSystem/cda-import-condition|same-source"
        ))

    @patch("fhir.bundle.requests.get")
    def test_consent_reuses_legacy_resource_without_identifier(self, mock_get):
        consent = {
            "resourceType": "Consent", "status": "active",
            "patient": {"reference": "Patient/p1"},
            "policyRule": {"text": "Synthetic directive"},
        }
        identifier_lookup = Mock()
        identifier_lookup.json.return_value = {"entry": []}
        content_lookup = Mock()
        content_lookup.json.return_value = {"entry": [
            {"resource": {
                **consent, "id": "legacy-consent",
                "text": {"status": "generated", "div": "<div>Generated</div>"},
            }},
        ]}
        mock_get.side_effect = [identifier_lookup, content_lookup]
        resource = {
            **consent,
            "identifier": [{
                "system": "https://fhir.omnilink.ch/fhir/NamingSystem/cda-import-consent",
                "value": "new-identity",
            }],
        }

        entry = build_bundle_entry(resource)

        self.assertEqual(entry["request"]["url"], "Consent/legacy-consent")
        self.assertEqual(mock_get.call_args.kwargs["params"]["patient"], "Patient/p1")

    @patch("fhir.bundle.requests.get")
    def test_consent_lookup_preserves_distinct_content_and_patient(self, mock_get):
        from fhir.bundle import _find_existing_consent_id

        target = {
            "resourceType": "Consent", "status": "active",
            "patient": {"reference": "Patient/p1"},
            "policyRule": {"text": "Synthetic directive"},
        }
        response = Mock()
        response.json.return_value = {"entry": [
            {"resource": {**target, "id": "other-patient",
                          "patient": {"reference": "Patient/p2"}}},
            {"resource": {**target, "id": "other-content",
                          "policyRule": {"text": "Different directive"}}},
        ]}
        mock_get.return_value = response

        self.assertIsNone(_find_existing_consent_id(target))

    @patch("fhir.bundle.requests.get")
    def test_consent_lookup_follows_pages_and_rejects_untrusted_links(self, mock_get):
        from config import FHIR_BASE
        from fhir.bundle import _find_existing_consent_id

        target = {
            "resourceType": "Consent", "status": "active",
            "patient": {"reference": "Patient/p1"},
        }
        first = Mock()
        first.json.return_value = {
            "link": [{"relation": "next", "url": FHIR_BASE.rstrip("/") + "/?_page=2"}],
        }
        second = Mock()
        second.json.return_value = {"entry": [{"resource": {**target, "id": "page-2"}}]}
        mock_get.side_effect = [first, second]
        self.assertEqual(_find_existing_consent_id(target), "page-2")

        mock_get.side_effect = None
        first.json.return_value = {
            "link": [{"relation": "next", "url": "https://untrusted.example/Consent"}],
        }
        mock_get.return_value = first
        with self.assertRaisesRegex(ValueError, "pagination"):
            _find_existing_consent_id(target)

    @patch("fhir.bundle.requests.get")
    def test_build_bundle_entry_upserts_by_own_id_when_identifier_not_found(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"entry": []}
        mock_get.return_value = response

        resource = {
            "resourceType": "Encounter",
            "id": "enc-1",
            "identifier": [
                {
                    "system": "urn:oid:1.2.3",
                    "value": "abc",
                }
            ],
        }

        entry = build_bundle_entry(resource)

        self.assertEqual(entry["request"], {"method": "PUT", "url": "Encounter/enc-1"})
        self.assertEqual(entry["resource"]["text"]["status"], "generated")
        self.assertIn("Generated Narrative: Encounter", entry["resource"]["text"]["div"])
        mock_get.assert_called_once()

    @patch("fhir.bundle.requests.get")
    def test_build_bundle_entry_preserves_existing_narrative(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"entry": []}
        mock_get.return_value = response

        resource = {
            "resourceType": "Observation",
            "identifier": [{"system": "urn:test", "value": "obs-1"}],
            "text": {
                "status": "generated",
                "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">Original</div>",
            },
        }

        entry = build_bundle_entry(resource)

        self.assertEqual(
            entry["resource"]["text"]["div"],
            "<div xmlns=\"http://www.w3.org/1999/xhtml\">Original</div>",
        )

    @patch("fhir.bundle.requests.get")
    def test_build_bundle_entry_uses_put_by_id_when_identifier_found(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "entry": [
                {
                    "resource": {
                        "id": "enc-1"
                    }
                }
            ]
        }
        mock_get.return_value = response

        resource = {
            "resourceType": "Encounter",
            "identifier": [
                {
                    "system": "urn:oid:1.2.3",
                    "value": "abc",
                }
            ],
        }

        entry = build_bundle_entry(resource)

        self.assertEqual(entry["request"], {"method": "PUT", "url": "Encounter/enc-1"})
        self.assertEqual(entry["resource"]["id"], "enc-1")
        mock_get.assert_called_once()

    @patch("fhir.bundle.requests.get")
    def test_document_reference_falls_back_to_content_match_when_identifier_changed(self, mock_get):
        identifier_lookup = Mock()
        identifier_lookup.raise_for_status.return_value = None
        identifier_lookup.json.return_value = {"entry": []}

        content_lookup = Mock()
        content_lookup.raise_for_status.return_value = None
        content_lookup.json.return_value = {
            "entry": [
                {
                    "resource": {
                        "resourceType": "DocumentReference",
                        "id": "doc-1",
                        "subject": {"reference": "Patient/3254"},
                        "content": [
                            {
                                "attachment": {
                                    "contentType": "text/plain",
                                    "hash": "BdOxJBQEA5SOnXMccU+9fNGkQfk=",
                                    "size": 64,
                                    "title": "Verlauf",
                                }
                            }
                        ],
                    }
                }
            ]
        }

        mock_get.side_effect = [identifier_lookup, content_lookup]

        resource = {
            "resourceType": "DocumentReference",
            "identifier": [
                {
                    "system": "https://fhir.omnilink.ch/fhir/NamingSystem/cda-import-clinical-note",
                    "value": "new-hash-after-mapping-change",
                }
            ],
            "subject": {"reference": "Patient/3254"},
            "date": "2019-08-17T12:15:00+01:00",
            "type": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "56825-3",
                    }
                ]
            },
            "content": [
                {
                    "attachment": {
                        "contentType": "text/plain",
                        "hash": "BdOxJBQEA5SOnXMccU+9fNGkQfk=",
                        "size": 64,
                        "title": "Verlauf",
                    }
                }
            ],
        }

        entry = build_bundle_entry(resource)

        self.assertEqual(
            entry["request"],
            {
                "method": "PUT",
                "url": "DocumentReference/doc-1",
            },
        )
        self.assertEqual(entry["resource"]["id"], "doc-1")
        self.assertEqual(mock_get.call_count, 2)

        fallback_call = mock_get.call_args_list[1]
        self.assertEqual(
            fallback_call.kwargs["params"],
            {
                "patient": "3254",
                "date": "2019-08-17T12:15:00+01:00",
                "type": "http://loinc.org|56825-3",
            },
        )

    @patch("fhir.bundle.requests.get")
    def test_binary_uses_put_with_stable_id(self, mock_get):
        resource = {
            "resourceType": "Binary",
            "id": "binary-a1b2c3",
            "contentType": "text/plain",
            "data": "YWJj",
        }

        entry = build_bundle_entry(resource)

        self.assertEqual(
            entry["request"],
            {
                "method": "PUT",
                "url": "Binary/binary-a1b2c3",
            },
        )
        self.assertNotIn("text", entry["resource"])
        mock_get.assert_not_called()

    @patch("fhir.bundle.requests.get")
    def test_code_lookup_uses_put_when_observation_exists(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "entry": [
                {
                    "resource": {
                        "id": "obs-100"
                    }
                }
            ]
        }
        mock_get.return_value = response

        resource = {
            "resourceType": "Observation",
            "subject": {
                "reference": "Patient/3192"
            },
            "effectiveDateTime": "2026-07-29T10:00:00+02:00",
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "29463-7",
                    }
                ]
            },
        }

        entry = build_bundle_entry(resource)

        self.assertEqual(
            entry["request"],
            {
                "method": "PUT",
                "url": "Observation/obs-100",
            },
        )

        self.assertEqual(
            mock_get.call_args.kwargs["params"],
            {
                "code": "http://loinc.org|29463-7",
                "_count": "1",
                "subject": "3192",
                "date": "2026-07-29T10:00:00+02:00",
            },
        )