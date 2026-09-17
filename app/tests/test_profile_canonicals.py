import unittest

from builders.ch_core_organization_builder import build_ch_core_organization
from builders.ch_core_practitioner_builder import build_ch_core_practitioner
from builders.ch_core_related_person_builder import build_ch_core_related_persons
from domain.organization import Organization
from domain.patient import HumanName, PatientContact
from domain.practitioner import PractitionerData
from mappers.allergy_mapper import map_allergy_section
from mappers.immunization_mapper import map_immunization_section
from mappers.medication_mapper import map_medication_section


class ProfileCanonicalTests(unittest.TestCase):
    def test_allergy_mapper_sets_ch_core_profile(self):
        resources = map_allergy_section(
            section={"entries": [{}]},
            patient_reference="Patient/123",
            context={},
        )

        self.assertEqual(len(resources), 1)
        self.assertEqual(
            resources[0]["meta"]["profile"][0],
            "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-allergyintolerance",
        )

    def test_immunization_mapper_sets_ch_core_profile(self):
        resources = map_immunization_section(
            section={"entries": [{}]},
            patient_reference="Patient/123",
            context={},
        )

        self.assertEqual(len(resources), 1)
        self.assertEqual(
            resources[0]["meta"]["profile"][0],
            "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-immunization",
        )

    def test_medication_statement_mapper_sets_ch_core_profile(self):
        resources = map_medication_section(
            section={"entries": [{}]},
            patient_reference="Patient/123",
            context={},
        )

        self.assertEqual(len(resources), 1)
        self.assertEqual(
            resources[0]["meta"]["profile"][0],
            "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-medicationstatement",
        )

    def test_related_person_builder_sets_ch_core_profile(self):
        resources = build_ch_core_related_persons(
            patient_reference="Patient/123",
            contacts=[
                PatientContact(
                    name=HumanName(text="Claudia Example"),
                )
            ],
        )

        self.assertEqual(len(resources), 1)
        self.assertEqual(
            resources[0]["meta"]["profile"][0],
            "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-relatedperson",
        )

    def test_practitioner_builder_sets_ch_core_profile(self):
        resource = build_ch_core_practitioner(
            PractitionerData()
        )

        self.assertEqual(
            resource["meta"]["profile"][0],
            "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-practitioner",
        )

    def test_organization_builder_sets_ch_core_profile(self):
        resource = build_ch_core_organization(
            Organization()
        )

        self.assertEqual(
            resource["meta"]["profile"][0],
            "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-organization",
        )


if __name__ == "__main__":
    unittest.main()
