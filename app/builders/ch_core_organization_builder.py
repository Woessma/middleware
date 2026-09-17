from domain.organization import Organization
from fhir.identifiers import build_cda_identifier


def build_ch_core_organization(
    org: Organization
) -> dict:

    resource = {
        "resourceType": "Organization",
        "meta": {
            "profile": [
                "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-organization"
            ]
        }
    }

    if org.identifier_root:
        identifier = build_cda_identifier(
            org.identifier_root,
            org.identifier_value
        )
        if org.identifier_root == "2.51.1.3":
            identifier["use"] = "official"
        resource["identifier"] = [identifier]

    if org.name:
        resource["name"] = org.name

    if org.telecom:

        telecom = org.telecom
        system = "other"

        if telecom.startswith("tel:"):
            system = "phone"
            telecom = telecom.replace("tel:", "")

        elif telecom.startswith("mailto:"):
            system = "email"
            telecom = telecom.replace("mailto:", "")

        resource["telecom"] = [
            {
                "system": system,
                "value": telecom
            }
        ]

    address = {}

    if org.street:
        address["line"] = [org.street]

    if org.postal_code:
        address["postalCode"] = org.postal_code

    if org.city:
        address["city"] = org.city

    if org.country:
        address["country"] = org.country

    if address:
        resource["address"] = [address]

    return resource
