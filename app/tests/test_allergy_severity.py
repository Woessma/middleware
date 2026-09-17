import unittest
import xml.etree.ElementTree as ET

from parser.cda.section_parser import extract_entry_summary
from mappers.allergy_mapper import map_allergy_section


class AllergySeverityTests(unittest.TestCase):
    def test_severity_relation_is_mapped_to_fhir(self):
        xml = '''
        <ClinicalDocument xmlns="urn:hl7-org:v3">
          <component>
            <structuredBody>
              <section>
                <entry>
                  <act classCode="ACT" moodCode="EVN">
                    <entryRelationship typeCode="COMP">
                      <observation classCode="OBS" moodCode="EVN">
                        <code code="419199007" codeSystem="2.16.840.1.113883.6.96" />
                        <statusCode code="completed" />
                        <entryRelationship typeCode="SEV">
                          <observation classCode="OBS" moodCode="EVN">
                            <code code="SEV" codeSystem="2.16.840.1.113883.5.4" />
                            <value xsiType="CD" code="24484000" codeSystem="2.16.840.1.113883.6.96" displayName="Severe" />
                          </observation>
                        </entryRelationship>
                      </observation>
                    </entryRelationship>
                  </act>
                </entry>
              </section>
            </structuredBody>
          </component>
        </ClinicalDocument>
        '''

        root = ET.fromstring(xml)
        section = root.find('.//{urn:hl7-org:v3}section')
        entry = section.find('{urn:hl7-org:v3}entry')

        parsed = extract_entry_summary(entry, section_code='48765-2', narrative_texts={})
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.get('severity', {}).get('code'), '24484000')

        resources = map_allergy_section(
            {'entries': [parsed]},
            'Patient/123',
            {}
        )
        self.assertEqual(resources[0]['severity'], 'severe')

    def test_severity_observation_with_code_sev_under_subj_is_mapped(self):
        xml = '''
        <ClinicalDocument xmlns="urn:hl7-org:v3">
          <component>
            <structuredBody>
              <section>
                <entry>
                  <act classCode="ACT" moodCode="EVN">
                    <entryRelationship typeCode="COMP">
                      <observation classCode="OBS" moodCode="EVN">
                        <code code="419199007" codeSystem="2.16.840.1.113883.6.96" />
                        <statusCode code="completed" />
                      </observation>
                    </entryRelationship>
                    <entryRelationship typeCode="SUBJ" inversionInd="true">
                      <observation classCode="OBS" moodCode="EVN">
                        <code code="SEV" codeSystem="2.16.840.1.113883.5.4" />
                        <text><reference value="#sev1" /></text>
                        <value xsiType="CD" code="255604002" codeSystem="2.16.840.1.113883.6.96" />
                      </observation>
                    </entryRelationship>
                  </act>
                </entry>
              </section>
            </structuredBody>
          </component>
        </ClinicalDocument>
        '''

        root = ET.fromstring(xml)
        section = root.find('.//{urn:hl7-org:v3}section')
        entry = section.find('{urn:hl7-org:v3}entry')

        parsed = extract_entry_summary(
            entry,
            section_code='48765-2',
            narrative_texts={'sev1': 'Schweregrad: mittel'}
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.get('severity', {}).get('code'), '255604002')

        resources = map_allergy_section(
            {'entries': [parsed]},
            'Patient/123',
            {}
        )
        self.assertEqual(resources[0]['severity'], 'moderate')

    def test_severity_is_parsed_when_main_node_is_observation(self):
        xml = '''
        <ClinicalDocument xmlns="urn:hl7-org:v3" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
          <component>
            <structuredBody>
              <section>
                <entry>
                  <observation classCode="OBS" moodCode="EVN">
                    <code code="419199007" codeSystem="2.16.840.1.113883.6.96" />
                    <statusCode code="completed" />
                    <entryRelationship typeCode="SUBJ" inversionInd="true">
                      <observation classCode="OBS" moodCode="EVN">
                        <code code="SEV" codeSystem="2.16.840.1.113883.5.4" />
                        <text><reference value="#sev1" /></text>
                        <value xsi:type="CD" code="255604002" codeSystem="2.16.840.1.113883.6.96" />
                      </observation>
                    </entryRelationship>
                  </observation>
                </entry>
              </section>
            </structuredBody>
          </component>
        </ClinicalDocument>
        '''

        root = ET.fromstring(xml)
        section = root.find('.//{urn:hl7-org:v3}section')
        entry = section.find('{urn:hl7-org:v3}entry')

        parsed = extract_entry_summary(
            entry,
            section_code='48765-2',
            narrative_texts={'sev1': 'Schweregrad: mittel'}
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.get('severity', {}).get('code'), '255604002')

        resources = map_allergy_section(
            {'entries': [parsed]},
            'Patient/123',
            {}
        )
        self.assertEqual(resources[0]['severity'], 'moderate')

    def test_severity_is_parsed_from_nested_reaction_observation(self):
        xml = '''
        <ClinicalDocument xmlns="urn:hl7-org:v3" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
          <component>
            <structuredBody>
              <section>
                <entry>
                  <act classCode="ACT" moodCode="EVN">
                    <entryRelationship typeCode="SUBJ">
                      <observation classCode="OBS" moodCode="EVN">
                        <code code="419199007" codeSystem="2.16.840.1.113883.6.96" />
                        <statusCode code="completed" />
                        <entryRelationship typeCode="MFST" inversionInd="true">
                          <observation classCode="OBS" moodCode="EVN">
                            <code code="418799008" codeSystem="2.16.840.1.113883.6.96" />
                            <text><reference value="#react1" /></text>
                            <value xsi:type="CD" code="267036007" codeSystem="2.16.840.1.113883.6.96" />
                            <entryRelationship typeCode="SUBJ" inversionInd="true">
                              <observation classCode="OBS" moodCode="EVN">
                                <code code="SEV" codeSystem="2.16.840.1.113883.5.4" />
                                <text><reference value="#sev1" /></text>
                                <value xsi:type="CD" code="255604002" codeSystem="2.16.840.1.113883.6.96" />
                              </observation>
                            </entryRelationship>
                          </observation>
                        </entryRelationship>
                      </observation>
                    </entryRelationship>
                  </act>
                </entry>
              </section>
            </structuredBody>
          </component>
        </ClinicalDocument>
        '''

        root = ET.fromstring(xml)
        section = root.find('.//{urn:hl7-org:v3}section')
        entry = section.find('{urn:hl7-org:v3}entry')

        parsed = extract_entry_summary(
            entry,
            section_code='48765-2',
            narrative_texts={'react1': 'Reaktion: Larynxödem', 'sev1': 'Schweregrad: mittel'}
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.get('severity', {}).get('code'), '255604002')

        resources = map_allergy_section(
            {'entries': [parsed]},
            'Patient/123',
            {}
        )
        self.assertEqual(resources[0]['severity'], 'moderate')

    def test_epic_style_textual_severity_is_mapped(self):
        xml = '''
        <ClinicalDocument xmlns="urn:hl7-org:v3" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
          <component>
            <structuredBody>
              <section>
                <entry>
                  <act classCode="ACT" moodCode="EVN">
                    <entryRelationship typeCode="SUBJ">
                      <observation classCode="OBS" moodCode="EVN">
                        <code code="ASSERTION" codeSystem="2.16.840.1.113883.5.4" />
                        <statusCode code="completed" />
                        <text>Kakao Angstzustände, Schwindel Hoch 06.02.2023</text>
                        <value xsi:type="CD" code="416098002" codeSystem="2.16.840.1.113883.6.96" displayName="Drug Allergy" />
                      </observation>
                    </entryRelationship>
                  </act>
                </entry>
              </section>
            </structuredBody>
          </component>
        </ClinicalDocument>
        '''

        root = ET.fromstring(xml)
        section = root.find('.//{urn:hl7-org:v3}section')
        entry = section.find('{urn:hl7-org:v3}entry')

        parsed = extract_entry_summary(
            entry,
            section_code='48765-2',
            narrative_texts={}
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.get('severity', {}).get('code'), '24484000')

        resources = map_allergy_section(
            {'entries': [parsed]},
            'Patient/123',
            {}
        )
        self.assertEqual(resources[0]['severity'], 'severe')

    def test_life_threatening_criticality_is_mapped_to_high(self):
        entry = {
            'criticality': {
                'code': '723509005',
                'displayName': 'Lebensbedrohlich',
                'text': 'Lebensbedrohlich'
            }
        }

        resources = map_allergy_section(
            {'entries': [entry]},
            'Patient/123',
            {}
        )

        self.assertEqual(resources[0]['criticality'], 'high')


if __name__ == '__main__':
    unittest.main()
