from parser.cda.section_parser import extract_entry_summary


def test_reaction_value_uses_resolved_narrative_text():
    xml = '''
    <ClinicalDocument xmlns="urn:hl7-org:v3">
      <component>
        <structuredBody>
          <section>
            <text>
              <content ID="react1">Reaktion: Larynxödem</content>
            </text>
            <entry>
              <act classCode="ACT" moodCode="EVN">
                <entryRelationship typeCode="COMP">
                  <observation classCode="OBS" moodCode="EVN">
                    <code code="419199007" codeSystem="2.16.840.1.113883.6.96" />
                    <text>
                      <reference value="#react1" />
                    </text>
                    <statusCode code="completed" />
                  </observation>
                </entryRelationship>
              </act>
            </entry>
          </section>
        </structuredBody>
      </component>
    </ClinicalDocument>
    '''

    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml)
    section = root.find('.//{urn:hl7-org:v3}section')
    entry = section.find('{urn:hl7-org:v3}entry')

    from parser.cda.helpers import collect_narrative_texts
    narrative_texts = collect_narrative_texts(section)
    result = extract_entry_summary(entry, section_code='48765-2', narrative_texts=narrative_texts)

    assert result is not None
    assert result['reactions'][0]['text'] == 'Reaktion: Larynxödem'
