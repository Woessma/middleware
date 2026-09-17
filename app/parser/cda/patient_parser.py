import xml.etree.ElementTree as ET
from parser.cda.constants import NS
from fhir.fhir_helpers import oid_to_fhir_system

from domain.patient import (
    PatientData,
    Identifier,
    HumanName,
    Address,
    Telecom,
    CodeableConcept,
    PatientCommunication,
    PatientContact,
)


CH_ECH_11_CONTACT_DATA_CODING = {
    "system": "http://fhir.ch/ig/ch-core/CodeSystem/ech-11",
    "code": "contactData",
    "display": "contact data",
}
CONTACT_CATEGORY_SYSTEM = "https://woess.ch/fhir/CodeSystem/patient-contact-category"


def parse_identifier_elements(parent: ET.Element | None) -> list[Identifier]:

    if parent is None:
        return []

    identifiers = []

    for identifier in parent.findall(
        "hl7:id",
        NS,
    ):
        root_oid = identifier.attrib.get("root")
        extension = identifier.attrib.get("extension")

        if identifier.attrib.get("nullFlavor"):
            continue

        if not extension and root_oid:
            extension = root_oid

        if not extension:
            continue

        identifiers.append(
            Identifier(
                system=f"urn:oid:{root_oid}"
                if root_oid else "unknown",
                value=extension,
                type=make_identifier_type(root_oid),
            )
        )

    return identifiers



def map_gender(code: str) -> str:

    mapping = {
        "M": "male",
        "m": "male",
        "F": "female",
        "f": "female",
        "U": "unknown",
        "u": "unknown",
        "O": "other",
        "o": "other"
    }

    return mapping.get(
        code,
        "unknown"
    )


def map_contact_point_use(code: str | None) -> str | None:

    if not code:
        return None

    mapping = {
        "H": "home",
        "HP": "home",
        "HV": "home",
        "WP": "work",
        "DIR": "work",
        "MC": "mobile",
        "TMP": "temp",
        "OLD": "old",
    }

    return mapping.get(code)


def map_address_use(code: str | None) -> str | None:

    if not code:
        return None

    mapping = {
        "H": "home",
        "HP": "home",
        "HV": "home",
        "WP": "work",
        "TMP": "temp",
        "OLD": "old",
    }

    return mapping.get(code)


def map_name_use(code: str | None) -> str | None:

    if not code:
        return None

    mapping = {
        "L": "official",
        "C": "usual",
        "P": "nickname",
        "A": "anonymous",
        "OLD": "old",
    }

    return mapping.get(code)


def make_codeable_concept(element: ET.Element | None) -> CodeableConcept | None:

    if element is None:
        return None

    code = element.attrib.get("code")
    display = element.attrib.get("displayName")
    system = oid_to_fhir_system(
        element.attrib.get("codeSystem")
    )

    if not any([code, display, system]):
        return None

    return CodeableConcept(
        code=code,
        display=display,
        system=system,
        text=display,
    )


def parse_human_name_element(name: ET.Element | None) -> HumanName | None:

    if name is None:
        return None

    family_names = [
        family.text.strip()
        for family in name.findall(
            "hl7:family",
            NS
        )
        if family.text and family.text.strip()
    ]

    given_names = [
        given.text.strip()
        for given in name.findall(
            "hl7:given",
            NS
        )
        if given.text and given.text.strip()
    ]

    prefixes = [
        prefix.text.strip()
        for prefix in name.findall(
            "hl7:prefix",
            NS
        )
        if prefix.text and prefix.text.strip()
    ]

    suffixes = [
        suffix.text.strip()
        for suffix in name.findall(
            "hl7:suffix",
            NS
        )
        if suffix.text and suffix.text.strip()
    ]

    name_text = " ".join(
        text.strip()
        for text in name.itertext()
        if text and text.strip()
    ) or None

    if not any([
        family_names,
        given_names,
        prefixes,
        suffixes,
        name_text,
    ]):
        return None

    return HumanName(
        family=family_names[0] if family_names else None,
        given=given_names,
        use=map_name_use(
            name.attrib.get("use")
        ),
        prefix=prefixes,
        suffix=suffixes,
        text=name_text,
    )


def make_identifier_type(root_oid: str | None) -> CodeableConcept | None:

    if not root_oid:
        return None

    if root_oid == "2.16.756.5.32":
        return CodeableConcept(
            text="AHVN13 / NAVS13"
        )

    if root_oid == "2.16.756.5.30.1.127.3.10.3":
        return CodeableConcept(
            text="EPR-SPID"
        )

    if root_oid == "2.16.756.5.30.1.123.100.1.1.1":
        return CodeableConcept(
            text="Insurance card number"
        )

    return CodeableConcept(
        code="MR",
        system="http://terminology.hl7.org/CodeSystem/v2-0203",
        display="Medical record number",
        text="Local patient identifier",
    )


def parse_bool(value: str | None) -> bool | None:

    if value is None:
        return None

    normalized = value.strip().lower()

    if normalized == "true":
        return True

    if normalized == "false":
        return False

    return None


def parse_address_element(addr: ET.Element | None) -> Address | None:

    if addr is None:
        return None

    lines = [
        line.text.strip()
        for line in addr.findall(
            "hl7:streetAddressLine",
            NS
        )
        if line.text and line.text.strip()
    ]

    text = None

    if addr.text and addr.text.strip():
        text = addr.text.strip()

    city = addr.findtext(
        "hl7:city",
        default=None,
        namespaces=NS
    )

    postal_code = addr.findtext(
        "hl7:postalCode",
        default=None,
        namespaces=NS
    )

    state = addr.findtext(
        "hl7:state",
        default=None,
        namespaces=NS
    )

    country = addr.findtext(
        "hl7:country",
        default=None,
        namespaces=NS
    )

    address = Address(
        lines=lines,
        use=map_address_use(
            addr.attrib.get("use")
        ),
        postal_code=postal_code,
        city=city,
        state=state,
        country=country,
        text=text,
    )

    if any([
        address.lines,
        address.use,
        address.postal_code,
        address.city,
        address.state,
        address.country,
        address.text,
    ]):
        return address

    return None


def parse_telecom_element(telecom: ET.Element | None) -> Telecom | None:

    if telecom is None:
        return None

    value = telecom.attrib.get("value")

    if not value:
        return None

    if value.startswith("tel:"):
        system = "phone"
        normalized_value = value.replace("tel:", "").strip()
    elif value.startswith("mailto:"):
        system = "email"
        normalized_value = value.replace("mailto:", "").strip()
    elif value.startswith("http://") or value.startswith("https://"):
        system = "url"
        normalized_value = value.strip()
    elif value.startswith("fax:"):
        system = "fax"
        normalized_value = value.replace("fax:", "").strip()
    else:
        system = "other"
        normalized_value = value.strip()

    return Telecom(
        system=system,
        value=normalized_value,
        use=map_contact_point_use(
            telecom.attrib.get("use")
        ),
    )


def parse_patient(root: ET.Element) -> PatientData:

    patient = PatientData()

    patient_role = root.find(
        ".//hl7:recordTarget/hl7:patientRole",
        NS
    )

    if patient_role is None:
        return patient

    # Identifier
    for identifier in patient_role.findall(
        "hl7:id",
        NS
    ):

        root_oid = identifier.attrib.get("root")
        extension = identifier.attrib.get("extension")

        if extension:

            patient.identifiers.append(
                Identifier(
                    system=f"urn:oid:{root_oid}"
                    if root_oid
                    else "unknown",
                    value=extension,
                    type=make_identifier_type(root_oid),
                )
            )
        #
        # CH-Core Identifier erkennen
        #

        if root_oid == "2.16.756.5.32":
            patient.ahvn13 = extension

        elif root_oid == "2.16.756.5.30.1.127.3.10.3":
            patient.epr_spid = extension

        elif root_oid == "2.16.756.5.30.1.123.100.1.1.1":
            patient.insurance_card_number = extension

    patient_element = patient_role.find(
        "hl7:patient",
        NS
    )

    if patient_element is None:
        return patient

    #
    # Address
    #
    for addr in patient_role.findall(
        "hl7:addr",
        NS
    ):
        address = parse_address_element(addr)

        if address:
            patient.addresses.append(address)

    #
    # Telecom
    #

    for telecom in patient_role.findall(
        "hl7:telecom",
        NS
    ):
        parsed_telecom = parse_telecom_element(telecom)

        if parsed_telecom:
            patient.telecoms.append(parsed_telecom)


    # Gender
    gender = patient_element.find(
        "hl7:administrativeGenderCode",
        NS
    )

    
    if gender is not None:

        patient.gender = map_gender(
            gender.attrib.get("code", "")
        )


    # Birth Date
    birth_time = patient_element.find(
        "hl7:birthTime",
        NS
    )

    if birth_time is not None:

        birth_value = birth_time.attrib.get(
            "value"
        )

        if birth_value:

            if len(birth_value) >= 8:

                patient.birth_date = (
                    f"{birth_value[0:4]}-"
                    f"{birth_value[4:6]}-"
                    f"{birth_value[6:8]}"
                )

            else:
                patient.birth_date = birth_value

    deceased_ind = patient_element.find(
        "./{*}deceasedInd"
    )

    if deceased_ind is not None:
        patient.deceased = parse_bool(
            deceased_ind.attrib.get("value")
        )

    patient.marital_status = make_codeable_concept(
        patient_element.find(
            "hl7:maritalStatusCode",
            NS
        )
    )

    patient.religion = make_codeable_concept(
        patient_element.find(
            "hl7:religiousAffiliationCode",
            NS
        )
    )

    # Names
    for name in patient_element.findall(
        "hl7:name",
        NS
    ):

        parsed_name = parse_human_name_element(name)

        if parsed_name is None:
            continue

        family_names = [
            family.text.strip()
            for family in name.findall(
                "hl7:family",
                NS
            )
            if family.text and family.text.strip()
        ]

        patient.names.append(parsed_name)

        for additional_family in family_names[1:]:
            patient.names.append(
                HumanName(
                    family=additional_family,
                    given=parsed_name.given,
                    use="old",
                    prefix=parsed_name.prefix,
                    suffix=parsed_name.suffix,
                    text=parsed_name.text,
                )
            )

    birth_place_addr = patient_element.find(
        "hl7:birthplace/hl7:place/hl7:addr",
        NS
    )

    patient.place_of_birth = parse_address_element(
        birth_place_addr
    )

    for language in patient_element.findall(
        "hl7:languageCommunication",
        NS
    ):
        language_code = language.find(
            "hl7:languageCode",
            NS
        )

        if language_code is None:
            continue

        code = language_code.attrib.get("code")

        if not code:
            continue

        patient.communications.append(
            PatientCommunication(
                language=CodeableConcept(
                    code=code,
                    system=oid_to_fhir_system(
                        language_code.attrib.get("codeSystem")
                    ) or "urn:ietf:bcp:47",
                    text=code,
                ),
                preferred=parse_bool(
                    language.find(
                        "hl7:preferenceInd",
                        NS
                    ).attrib.get("value")
                ) if language.find(
                    "hl7:preferenceInd",
                    NS
                ) is not None else None,
            )
        )

    for guardian in patient_element.findall(
        "hl7:guardian",
        NS
    ):
        guardian_name_node = guardian.find(
            "hl7:guardianPerson/hl7:name",
            NS
        )

        guardian_name = None

        if guardian_name_node is not None:
            given_names = [
                given.text.strip()
                for given in guardian_name_node.findall(
                    "hl7:given",
                    NS
                )
                if given.text and given.text.strip()
            ]

            family_node = guardian_name_node.find(
                "hl7:family",
                NS
            )

            guardian_name = HumanName(
                family=family_node.text.strip()
                if family_node is not None and family_node.text
                else None,
                given=given_names,
            )

        guardian_contact = PatientContact(
            relationship=CodeableConcept(
                code="GUARD",
                system="http://terminology.hl7.org/CodeSystem/v3-RoleCode",
                display="guardian",
                text="guardian",
            ),
            name=guardian_name,
            address=parse_address_element(
                guardian.find(
                    "hl7:addr",
                    NS
                )
            ),
        )

        for telecom in guardian.findall(
            "hl7:telecom",
            NS
        ):
            parsed_telecom = parse_telecom_element(telecom)

            if parsed_telecom:
                guardian_contact.telecoms.append(
                    parsed_telecom
                )

        if any([
            guardian_contact.relationship,
            guardian_contact.name,
            guardian_contact.address,
            guardian_contact.telecoms,
        ]):
            patient.contacts.append(
                guardian_contact
            )

    for participant in root.findall(
        ".//hl7:participant[@typeCode='IND']/hl7:associatedEntity",
        NS,
    ):
        contact_category = participant.attrib.get("classCode")
        relationship_code = participant.find(
            "hl7:code",
            NS,
        )

        original_text = participant.findtext(
            "hl7:code/hl7:originalText",
            default=None,
            namespaces=NS,
        )

        relationship = CodeableConcept(
            text=original_text or (
                relationship_code.attrib.get("displayName")
                if relationship_code is not None else None
            ),
            codings=[CH_ECH_11_CONTACT_DATA_CODING],
        )

        if contact_category == "ECON":
            relationship.text = "Notfallkontakt"
            relationship.codings.append({
                "system": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
                "code": "ECON",
                "display": "Emergency contact",
            })
        else:
            relationship.codings.append({
                "system": CONTACT_CATEGORY_SYSTEM,
                "code": "other",
                "display": "Andere Kontakte",
            })

        if relationship_code is not None:
            role_coding = {
                "system": oid_to_fhir_system(
                    relationship_code.attrib.get("codeSystem")
                ),
                "code": relationship_code.attrib.get("code"),
                "display": relationship_code.attrib.get("displayName"),
            }
            filtered_role_coding = {
                key: value
                for key, value in role_coding.items()
                if value is not None
            }

            # Avoid a semantically empty coding with only "system".
            if filtered_role_coding.get("code") or filtered_role_coding.get("display"):
                relationship.codings.append(
                    filtered_role_coding
                )

        contact = PatientContact(
            relationship=relationship,
            name=parse_human_name_element(
                participant.find(
                    "hl7:associatedPerson/hl7:name",
                    NS,
                )
            ),
            address=parse_address_element(
                participant.find(
                    "hl7:addr",
                    NS,
                )
            ),
            identifiers=parse_identifier_elements(
                participant
            ),
        )

        for telecom in participant.findall(
            "hl7:telecom",
            NS,
        ):
            parsed_telecom = parse_telecom_element(telecom)

            if parsed_telecom:
                contact.telecoms.append(parsed_telecom)

        if any([
            contact.relationship,
            contact.name,
            contact.address,
            contact.telecoms,
        ]):
            patient.contacts.append(contact)

    return patient