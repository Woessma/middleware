import unittest

from mappers.social_history_mapper import map_social_history_section


class SocialHistoryMapperTests(unittest.TestCase):
    def test_preserves_question_and_value_codings(self):
        resources = map_social_history_section(
            {
                "entries": [{
                    "code": {
                        "code": "72166-2",
                        "codeSystem": "2.16.840.1.113883.6.1",
                        "displayName": "Tobacco smoking status NHIS",
                    },
                    "value": {
                        "code": "266927001",
                        "codeSystem": "2.16.840.1.113883.6.96",
                        "displayName": "Tobacco smoking consumption unknown",
                    },
                }],
            },
            "Patient/3323",
            {},
        )

        observation = resources[0]

        self.assertEqual(
            observation["category"][0]["coding"][0]["code"],
            "social-history",
        )
        self.assertEqual(
            observation["code"]["coding"][0],
            {
                "system": "http://loinc.org",
                "code": "72166-2",
                "display": "Tobacco smoking status NHIS",
            },
        )
        self.assertEqual(
            observation["valueCodeableConcept"]["coding"][0],
            {
                "system": "http://snomed.info/sct",
                "code": "266927001",
                "display": "Tobacco smoking consumption unknown",
            },
        )

    def test_keeps_uncoded_narrative_values_as_strings(self):
        resources = map_social_history_section(
            {
                "entries": [{
                    "code": {
                        "code": "76689-9",
                        "codeSystem": "2.16.840.1.113883.6.1",
                        "displayName": "Sex assigned at birth",
                    },
                    "value": {
                        "text": "Nicht vorhanden",
                        "nullFlavor": "UNK",
                    },
                }],
            },
            "Patient/3323",
            {},
        )

        observation = resources[0]

        self.assertEqual(
            observation["code"]["coding"][0]["code"],
            "76689-9",
        )
        self.assertEqual(observation["valueString"], "Nicht vorhanden")
        self.assertNotIn("valueCodeableConcept", observation)


if __name__ == "__main__":
    unittest.main()