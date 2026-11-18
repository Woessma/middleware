import unittest

from mappers.immunization_mapper import _build_vaccine_code_codings, map_immunization_section
from terminology.vacd import SWISSMEDIC_AUTHORIZED_VACCINES


class ImmunizationTerminologyTests(unittest.TestCase):
    def test_brand_alone_does_not_invent_swissmedic_or_formulation_specific_cvx(self):
        for name in (
            "PFIZER",
            "Pfizer COVID-19 Impfung",
            "COVID-19 Pfizer",
            "MODERNA",
            "COVID-19",
            "INFLUENZA",
            "INFLUENZA_IMPFUNG",
            "FSME",
        ):
            with self.subTest(name=name):
                codings = _build_vaccine_code_codings(None, name)
                self.assertFalse(any(c.get("system") == SWISSMEDIC_AUTHORIZED_VACCINES for c in codings))
                self.assertFalse(any(c.get("system") == "http://hl7.org/fhir/sid/cvx" for c in codings))

    def test_explicit_cvx_code_is_enriched_from_the_cdc_catalog_and_crosswalk(self):
        codings = _build_vaccine_code_codings(
            "207",
            None,
            "2.16.840.1.113883.12.292",
        )

        self.assertIn(
            {
                "system": "http://hl7.org/fhir/sid/cvx",
                "code": "207",
                "display": "SARS-COV-2 (COVID-19) vaccine, mRNA, spike protein, LNP, "
                "preservative free, 100 mcg/0.5mL dose or 50 mcg/0.25mL dose",
            },
            codings,
        )
        self.assertIn(
            {"system": "http://snomed.info/sct", "code": "1119349007"},
            [{key: value for key, value in coding.items() if key != "display"} for coding in codings],
        )

    def test_original_cvx_and_swissmedic_codes_are_preserved(self):
        for system, code in (("http://hl7.org/fhir/sid/cvx", "208"),
                             (SWISSMEDIC_AUTHORIZED_VACCINES, "source-product-code")):
            with self.subTest(system=system):
                codings = _build_vaccine_code_codings(code, "Pfizer COVID-19 Impfung", system)
                self.assertIn({"system": system, "code": code, "display": "Pfizer COVID-19 Impfung"}, codings)
                self.assertFalse(any(c.get("code") in ("COVID-19-PFIZER", "207") for c in codings))

    def test_non_cdc_conform_epic_cvx_codes_map_by_display_not_by_cdc_meaning(self):
        # Epic sends CVX 184 as "FSME" and 167 as "Diphtherie, Tetanus", while CDC
        # defines 184 = yellow fever and 167 = meningococcal. The display decides.
        for code, display, snomed in (
            ("184", "FSME", "836403007"),
            ("167", "Diphtherie, Tetanus", "871826000"),
        ):
            with self.subTest(code=code):
                codings = _build_vaccine_code_codings(
                    code, display, "2.16.840.1.113883.12.292"
                )
                self.assertIn(
                    {
                        "system": "http://hl7.org/fhir/sid/cvx",
                        "code": code,
                        "display": display,
                    },
                    codings,
                )
                self.assertIn(
                    {
                        "system": "http://snomed.info/sct",
                        "code": snomed,
                        "display": display,
                    },
                    codings,
                )

    def test_display_only_fsme_gets_antigen_level_snomed(self):
        codings = _build_vaccine_code_codings(None, "FSME")
        self.assertIn(
            {
                "system": "http://snomed.info/sct",
                "code": "836403007",
                "display": "FSME",
            },
            codings,
        )

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
