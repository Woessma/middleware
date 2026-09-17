from xml.etree import ElementTree as ET

from builders.ch_core_practitioner_builder import (
    build_ch_core_practitioner,
)
from domain.patient import Address, HumanName, Identifier, Telecom
from domain.practitioner import PractitionerData
from parser.cda.practitioner_parser import (
    FALLBACK_PRACTITIONER_SYSTEM,
    parse_practitioner,
)


def test_parse_mwo_practitioner_builds_fallback_identifier_when_cda_id_is_missing():
    root = ET.parse(
        "app/tests/data/CDA_MWO.xml"
    ).getroot()

    practitioner = parse_practitioner(root)

    assert practitioner.identifiers
    assert practitioner.identifiers[0].system == FALLBACK_PRACTITIONER_SYSTEM
    assert practitioner.identifiers[0].value
    assert practitioner.names[0].family == "Razzaghi"


def test_build_mwo_practitioner_contains_fallback_identifier():
    root = ET.parse(
        "app/tests/data/CDA_MWO.xml"
    ).getroot()

    resource = build_ch_core_practitioner(
        parse_practitioner(root)
    )

    assert resource["resourceType"] == "Practitioner"
    assert resource["identifier"][0]["system"] == FALLBACK_PRACTITIONER_SYSTEM
    assert resource["identifier"][0]["value"]
    assert resource["name"][0]["family"] == "Razzaghi"


def test_build_practitioner_dedupes_redundant_demographics():
    practitioner = PractitionerData(
        identifiers=[
            Identifier(system="urn:oid:9.8.7", value="17395"),
            Identifier(system="urn:oid:9.8.7", value="17395"),
        ],
        names=[
            HumanName(family="Razzaghi", given=["A"]),
            HumanName(family="Razzaghi", given=["A"]),
        ],
        telecoms=[
            Telecom(system="phone", value="+41-41-552-00-60"),
            Telecom(system="phone", value="+41-41-552-00-60", use="work"),
        ],
        addresses=[
            Address(lines=["Ringstrasse 37"], postal_code="6010", city="Kriens", country="CHE"),
            Address(lines=["Ringstrasse"], postal_code="6010", city="Kriens", country="CHE"),
        ],
    )

    resource = build_ch_core_practitioner(practitioner)

    assert len(resource["identifier"]) == 1
    assert len(resource["name"]) == 1
    assert len(resource["telecom"]) == 1
    assert resource["telecom"][0]["use"] == "work"
    assert len(resource["address"]) == 1
    assert resource["address"][0]["line"] == ["Ringstrasse 37"]