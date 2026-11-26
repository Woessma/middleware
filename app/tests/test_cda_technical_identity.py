import unittest

from services.cda_technical_identity import (
    CDA_TECHNICAL_EPIC_IDENTIFIER_SYSTEMS,
    CDA_TECHNICAL_SOURCE_SYSTEM,
    CdaTechnicalSourceConflict,
    attach_cda_technical_source_identifier,
    cda_technical_source_identifier,
)


EPIC = "urn:synthetic:epic"
OTHER_EPIC = "urn:synthetic:epic-other"


def patient(*identifiers):
    return {"resourceType": "Patient", "identifier": list(identifiers)}


class CdaTechnicalIdentityTests(unittest.TestCase):
    def test_same_epic_identity_has_stable_namespace_scoped_marker(self):
        source = {"system": EPIC, "value": "synthetic-patient"}
        first = cda_technical_source_identifier(patient(source), {EPIC, OTHER_EPIC})
        duplicate = cda_technical_source_identifier(
            patient(source, source, {"system": "urn:synthetic:other", "value": "irrelevant"}),
            {EPIC, OTHER_EPIC},
        )
        different_namespace = cda_technical_source_identifier(
            patient({"system": OTHER_EPIC, "value": source["value"]}),
            {EPIC, OTHER_EPIC},
        )
        self.assertEqual(first, duplicate)
        self.assertEqual(first["system"], CDA_TECHNICAL_SOURCE_SYSTEM)
        self.assertNotEqual(first, different_namespace)
        self.assertNotIn(source["value"], first["value"])

    def test_missing_ambiguous_or_invalid_epic_id_requires_review(self):
        for identifiers in (
            (),
            ({"system": EPIC, "value": "one"}, {"system": EPIC, "value": "two"}),
            ({"system": EPIC, "value": "one"}, {"system": OTHER_EPIC, "value": "one"}),
            ({"system": EPIC, "value": ""},),
            ({"system": EPIC, "value": " value "},),
        ):
            with self.subTest(identifiers=identifiers):
                with self.assertRaises(CdaTechnicalSourceConflict):
                    cda_technical_source_identifier(patient(*identifiers), {EPIC, OTHER_EPIC})

    def test_invalid_configuration_or_resource_is_not_a_missing_id(self):
        for resource, systems in (
            (patient(), set()),
            (patient(), {" "}),
            ({"resourceType": "Organization"}, {EPIC}),
            ({"resourceType": "Patient", "identifier": None}, {EPIC}),
            (patient({"system": [], "value": "one"}), {EPIC}),
        ):
            with self.subTest(resource=resource, systems=systems):
                with self.assertRaises(ValueError):
                    cda_technical_source_identifier(resource, systems)

    def test_luks_test_source_gets_an_idempotent_pseudonymous_marker(self):
        system = next(iter(CDA_TECHNICAL_EPIC_IDENTIFIER_SYSTEMS))
        source = {"system": system, "value": "synthetic-luks-test-patient"}
        resource = patient(source)

        attach_cda_technical_source_identifier(resource)
        first = next(
            item for item in resource["identifier"]
            if item.get("system") == CDA_TECHNICAL_SOURCE_SYSTEM
        )
        attach_cda_technical_source_identifier(resource)

        self.assertEqual(
            [
                item for item in resource["identifier"]
                if item.get("system") == CDA_TECHNICAL_SOURCE_SYSTEM
            ],
            [first],
        )
        self.assertNotIn(source["value"], first["value"])

    def test_attachment_skips_other_sources_and_rejects_untrusted_markers(self):
        other = patient({"system": "urn:synthetic:other", "value": "source"})
        attach_cda_technical_source_identifier(other)
        self.assertEqual(len(other["identifier"]), 1)

        system = next(iter(CDA_TECHNICAL_EPIC_IDENTIFIER_SYSTEMS))
        ambiguous = patient(
            {"system": system, "value": "first"},
            {"system": system, "value": "second"},
        )
        with self.assertRaises(CdaTechnicalSourceConflict):
            attach_cda_technical_source_identifier(ambiguous)

        forged = patient({
            "system": CDA_TECHNICAL_SOURCE_SYSTEM,
            "value": "unverified",
        })
        with self.assertRaises(CdaTechnicalSourceConflict):
            attach_cda_technical_source_identifier(forged)

        malformed = patient({"system": [], "value": "invalid"})
        with self.assertRaises(ValueError):
            attach_cda_technical_source_identifier(malformed)


if __name__ == "__main__":
    unittest.main()
