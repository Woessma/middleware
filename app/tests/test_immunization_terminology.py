import unittest

from mappers.immunization_mapper import _build_vaccine_code_codings, map_immunization_section
from terminology.vacd import SWISSMEDIC_AUTHORIZED_VACCINES


class ImmunizationTerminologyTests(unittest.TestCase):
    def test_brand_alone_does_not_invent_swissmedic_or_formulation_specific_cvx(self):
        for name in ("PFIZER", "Pfizer COVID-19 Impfung", "COVID-19 Pfizer", "MODERNA", "COVID-19"):
            with self.subTest(name=name):
                codings = _build_vaccine_code_codings(None, name)
                self.assertFalse(any(c.get("system") == SWISSMEDIC_AUTHORIZED_VACCINES for c in codings))
                self.assertFalse(any(c.get("system") == "http://hl7.org/fhir/sid/cvx" for c in codings))

    def test_original_cvx_and_swissmedic_codes_are_preserved(self):
        for system, code in (("http://hl7.org/fhir/sid/cvx", "208"),
                             (SWISSMEDIC_AUTHORIZED_VACCINES, "source-product-code")):
            with self.subTest(system=system):
                codings = _build_vaccine_code_codings(code, "Pfizer COVID-19 Impfung", system)
                self.assertIn({"system": system, "code": code, "display": "Pfizer COVID-19 Impfung"}, codings)
                self.assertFalse(any(c.get("code") in ("COVID-19-PFIZER", "207") for c in codings))

    def test_import_identity_and_source_metadata_do_not_change(self):
        section = {"entries": [{
            "id": {"root": "2.25.123", "extension": "synthetic-vaccination"},
            "effectiveTime": "20210101", "lotNumber": "synthetic-lot",
            "consumable": {"code": {"code": "208", "codeSystem": "2.16.840.1.113883.12.292",
                                     "displayName": "Pfizer COVID-19 Impfung"}},
        }]}
        resource = map_immunization_section(section, "Patient/synthetic", {})[0]
        self.assertEqual(resource["identifier"], [{"system": "urn:oid:2.25.123", "value": "synthetic-vaccination"}])
        self.assertEqual(resource["lotNumber"], "synthetic-lot")
        self.assertEqual(resource["occurrenceDateTime"], "2021-01-01")
        self.assertTrue(any(c.get("code") == "208" for c in resource["vaccineCode"]["coding"]))
