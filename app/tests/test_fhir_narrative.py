import unittest

from fhir.narrative import (
    build_list_narrative,
    build_text_narrative,
    build_xhtml_narrative,
    ensure_resource_narrative,
)


class FhirNarrativeTests(unittest.TestCase):
    def test_text_narrative_escapes_source_text(self):
        narrative = build_text_narrative("A < B & C")

        self.assertEqual(narrative["status"], "generated")
        self.assertEqual(
            narrative["div"],
            '<div xmlns="http://www.w3.org/1999/xhtml">A &lt; B &amp; C</div>',
        )

    def test_list_narrative_escapes_each_item(self):
        narrative = build_list_narrative(["A < B", "C & D"])

        self.assertEqual(
            narrative["div"],
            '<div xmlns="http://www.w3.org/1999/xhtml">'
            "<ul><li>A &lt; B</li><li>C &amp; D</li></ul></div>",
        )

    def test_xhtml_narrative_uses_shared_fhir_envelope(self):
        narrative = build_xhtml_narrative("<p>Generated</p>")

        self.assertEqual(narrative["status"], "generated")
        self.assertEqual(
            narrative["div"],
            '<div xmlns="http://www.w3.org/1999/xhtml"><p>Generated</p></div>',
        )

    def test_resource_narrative_keeps_shared_xhtml_envelope(self):
        resource = {"resourceType": "Condition", "code": {"text": "A < B"}}

        ensure_resource_narrative(resource)

        self.assertTrue(
            resource["text"]["div"].startswith(
                '<div xmlns="http://www.w3.org/1999/xhtml">'
            )
        )
        self.assertIn("A &lt; B", resource["text"]["div"])


if __name__ == "__main__":
    unittest.main()
