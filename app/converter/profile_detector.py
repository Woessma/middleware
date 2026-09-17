import xml.etree.ElementTree as ET
from parser.cda.constants import NS


def detect_profile(root):

    template_ids = [
        t.get("root")
        for t in root.findall(
            ".//hl7:templateId",
            NS
        )
    ]

    if "1.2.840.114350.1.72.1.51693" in template_ids:
        return {
            "vendor": "EPIC",
            "profile": "CCDA"
        }

    if any(
        root_name in template_ids
        for root_name in [
            "1.2.40.0.34.6.0.11.0.1",
            "1.2.40.0.34.7.22.1",
            "1.2.40.0.34.6.0.11.0.5",
            "1.2.40.0.34.6.0.11.0.5.0.3",
        ]
    ) or root.find(".//hl7at:formatCode", NS | {"hl7at": "urn:hl7-at:v3"}) is not None:
        return {
            "vendor": "HL7-AT",
            "profile": "ARZTBRIEF"
        }

    return {
        "vendor": "UNKNOWN",
        "profile": "GENERIC"
    }