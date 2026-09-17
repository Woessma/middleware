import xml.etree.ElementTree as ET
import hashlib
from parser.cda.constants import NS

from domain.practitioner import (
    PractitionerData,
)

from domain.patient import (
    Identifier,
    HumanName,
    Address,
    Telecom,
)


FALLBACK_PRACTITIONER_SYSTEM = (
    "https://woess.ch/fhir/NamingSystem/cda-import-practitioner"
)


def _build_fallback_practitioner_identifier(
    practitioner: PractitionerData,
) -> Identifier | None:

    fingerprint_parts = []

    for name in practitioner.names:
        if name.family:
            fingerprint_parts.append(name.family.strip().lower())

        fingerprint_parts.extend(
            given.strip().lower()
            for given in name.given
            if given and given.strip()
        )

    fingerprint_parts.extend(
        telecom.value.strip().lower()
        for telecom in practitioner.telecoms
        if telecom.value and telecom.value.strip()
    )

    for address in practitioner.addresses:
        fingerprint_parts.extend(
            line.strip().lower()
            for line in address.lines
            if line and line.strip()
        )

        for value in (
            address.postal_code,
            address.city,
            address.country,
        ):
            if value and value.strip():
                fingerprint_parts.append(
                    value.strip().lower()
                )

    if not fingerprint_parts:
        return None

    identifier_value = hashlib.sha256(
        "|".join(fingerprint_parts).encode("utf-8")
    ).hexdigest()

    return Identifier(
        system=FALLBACK_PRACTITIONER_SYSTEM,
        value=identifier_value,
    )


def parse_practitioner(
    root: ET.Element
) -> PractitionerData:

    practitioner = PractitionerData()

    #
    # PRIORITÄT 1:
    # EPIC serviceEvent performer
    #
    assigned_entity = root.find(
        ".//hl7:documentationOf/"
        "hl7:serviceEvent/"
        "hl7:performer/"
        "hl7:assignedEntity",
        NS
    )

    #
    # FALLBACK:
    # klassischer CDA Header Author
    #
    if assigned_entity is None:
        assigned_entity = root.find(
            ".//hl7:author/hl7:assignedAuthor",
            NS
        )

    if assigned_entity is None:
        return practitioner

    #
    # Identifier
    #
    for identifier in assigned_entity.findall(
        "hl7:id",
        NS
    ):

        root_oid = identifier.attrib.get(
            "root"
        )

        extension = identifier.attrib.get(
            "extension"
        )

        null_flavor = identifier.attrib.get(
            "nullFlavor"
        )

        if null_flavor:
            continue

        if not extension and root_oid:
            extension = root_oid

        if not extension:
            continue

        practitioner.identifiers.append(
            Identifier(
                system=f"urn:oid:{root_oid}",
                value=extension
            )
        )

        #
        # GLN
        #
        if root_oid == "2.51.1.3":
            practitioner.gln = extension

    #
    # Name
    #
    assigned_person = assigned_entity.find(
        "hl7:assignedPerson",
        NS
    )

    if assigned_person is not None:

        for name in assigned_person.findall(
            "hl7:name",
            NS
        ):

            family = None

            family_element = name.find(
                "hl7:family",
                NS
            )

            if (
                family_element is not None
                and family_element.text
            ):
                family = (
                    family_element.text.strip()
                )

            given_names = []

            for given in name.findall(
                "hl7:given",
                NS
            ):

                if given.text:
                    given_names.append(
                        given.text.strip()
                    )

            practitioner.names.append(
                HumanName(
                    family=family,
                    given=given_names
                )
            )

    #
    # Adresse
    #
    for addr in assigned_entity.findall(
        "hl7:addr",
        NS
    ):

        lines = []

        for line in addr.findall(
            "hl7:streetAddressLine",
            NS
        ):
            if line.text:
                lines.append(
                    line.text.strip()
                )

        postal_code = None
        city = None
        country = None

        postal = addr.find(
            "hl7:postalCode",
            NS
        )

        if postal is not None and postal.text:
            postal_code = postal.text.strip()

        city_element = addr.find(
            "hl7:city",
            NS
        )

        if (
            city_element is not None
            and city_element.text
        ):
            city = city_element.text.strip()

        country_element = addr.find(
            "hl7:country",
            NS
        )

        if (
            country_element is not None
            and country_element.text
        ):
            country = country_element.text.strip()

        practitioner.addresses.append(
            Address(
                lines=lines,
                postal_code=postal_code,
                city=city,
                country=country
            )
        )

    #
    # Telecom
    #
    for telecom in assigned_entity.findall(
        "hl7:telecom",
        NS
    ):

        value = telecom.attrib.get(
            "value"
        )

        if not value:
            continue

        system = None

        if value.startswith("tel:"):
            system = "phone"
            value = value.replace(
                "tel:",
                ""
            )

        elif value.startswith("mailto:"):
            system = "email"
            value = value.replace(
                "mailto:",
                ""
            )

        elif value.startswith("fax:"):
            system = "fax"
            value = value.replace(
                "fax:",
                ""
            )

        practitioner.telecoms.append(
            Telecom(
                system=system,
                value=value,
                use=None
            )
        )

    if not practitioner.identifiers:
        fallback_identifier = (
            _build_fallback_practitioner_identifier(
                practitioner
            )
        )

        if fallback_identifier:
            practitioner.identifiers.append(
                fallback_identifier
            )

    return practitioner