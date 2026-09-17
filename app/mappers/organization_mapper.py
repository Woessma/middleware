from domain.organization import Organization
from fhir.identifiers import get_cda_identifier_value


def organization_to_fhir_params(
    org: Organization
) -> dict:

    telecom = None

    if org.telecom:

        value = org.telecom
        system = "other"

        if value.startswith("tel:"):
            system = "phone"
            value = value.replace("tel:", "")

        elif value.startswith("mailto:"):
            system = "email"
            value = value.replace("mailto:", "")

        telecom = [
            {
                "system": system,
                "value": value
            }
        ]

    address = None

    if any([
        org.street,
        org.postal_code,
        org.city,
        org.country
    ]):
        address = {}

        if org.street:
            address["line"] = [org.street]

        if org.postal_code:
            address["postalCode"] = org.postal_code

        if org.city:
            address["city"] = org.city

        if org.country:
            address["country"] = org.country

    return {
        "identifier_system":
            f"urn:oid:{org.identifier_root}",
        "identifier_value":
            get_cda_identifier_value(
                org.identifier_root,
                org.identifier_value
            ),
        "name":
            org.name,
        "telecom":
            telecom,
        "address":
            address
    }