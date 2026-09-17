from domain.organization import Organization
from parser.cda.constants import NS


def parse_organization(org_node):

    if org_node is None:
        return None

    org = Organization()

    identifier = org_node.find("./hl7:id", NS)

    if identifier is not None:
        org.identifier_root = identifier.attrib.get("root")
        org.identifier_value = identifier.attrib.get("extension")

    name = org_node.find("./hl7:name", NS)

    if name is not None:
        org.name = name.text

    telecom = org_node.find("./hl7:telecom", NS)

    if telecom is not None:
        org.telecom = telecom.attrib.get("value")

    addr = org_node.find("./hl7:addr", NS)

    if addr is not None:

        street_line = addr.find("./hl7:streetAddressLine", NS)
        street_name = addr.find("./hl7:streetName", NS)
        house_number = addr.find("./hl7:houseNumber", NS)
        postal = addr.find("./hl7:postalCode", NS)
        city = addr.find("./hl7:city", NS)
        country = addr.find("./hl7:country", NS)

        if street_line is not None:
            org.street = street_line.text
        else:
            parts = [
                street_name.text if street_name is not None and street_name.text else None,
                house_number.text if house_number is not None and house_number.text else None,
            ]
            org.street = " ".join([part for part in parts if part]) or None

        org.postal_code = postal.text if postal is not None else None
        org.city = city.text if city is not None else None
        org.country = country.text if country is not None else None

    return org