
from parser.cda.constants import NS

from utils.fhir_utils import (
    cda_ts_to_fhir_datetime,
)


def text_or_none(element):
    if element is None:
        return None
    if element.text is None:
        return None
 
    value = element.text.strip()
    return value if value else None

def attr_or_none(element, attr):
    if element is None:
        return None
    return element.attrib.get(attr)

def collect_narrative_texts(section):
    result = {}
 
    text_node = section.find("hl7:text", NS)
 
    if text_node is None:
        return result
 
    for elem in text_node.iter():
        elem_id = elem.attrib.get("ID")
 
        if not elem_id:
            continue
 
        value = "".join(elem.itertext()).strip()
 
        if value:
            result[elem_id] = value
 
    return result

def resolve_reference_text(reference, narrative_texts):
    if not reference:
        return None
 
    ref_id = reference.replace("#", "")
 
    return narrative_texts.get(ref_id)