from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CodeableConcept:

    code: Optional[str] = None
    system: Optional[str] = None
    display: Optional[str] = None
    text: Optional[str] = None
    codings: list[dict] = field(default_factory=list)


@dataclass
class Identifier:

    system: str
    value: str
    use: Optional[str] = None
    type: Optional[CodeableConcept] = None


@dataclass
class HumanName:

    family: Optional[str] = None
    given: list[str] = field(default_factory=list)
    use: Optional[str] = None
    prefix: list[str] = field(default_factory=list)
    suffix: list[str] = field(default_factory=list)
    text: Optional[str] = None


@dataclass
class Telecom:

    system: str
    value: str
    use: Optional[str] = None


@dataclass
class Address:

    lines: list[str] = field(default_factory=list)

    use: Optional[str] = None

    postal_code: Optional[str] = None

    city: Optional[str] = None

    state: Optional[str] = None

    country: Optional[str] = None

    text: Optional[str] = None


@dataclass
class PatientCommunication:

    language: CodeableConcept
    preferred: Optional[bool] = None


@dataclass
class PatientContact:

    relationship: Optional[CodeableConcept] = None
    name: Optional[HumanName] = None
    address: Optional[Address] = None
    telecoms: list[Telecom] = field(default_factory=list)
    identifiers: list[Identifier] = field(default_factory=list)


@dataclass
class PatientData:

    # Status
    active: Optional[bool] = None
    deceased: Optional[bool] = None

    # Demografie
    gender: Optional[str] = None
    birth_date: Optional[str] = None
    marital_status: Optional[CodeableConcept] = None

    # Identifikatoren
    ahvn13: Optional[str] = None
    epr_spid: Optional[str] = None
    insurance_card_number: Optional[str] = None

    identifiers: list[Identifier] = field(
        default_factory=list
    )

    names: list[HumanName] = field(
        default_factory=list
    )

    addresses: list[Address] = field(
        default_factory=list
    )

    telecoms: list[Telecom] = field(
        default_factory=list
    )

    # Schweizer Erweiterungen
    place_of_birth: Optional[Address] = None

    place_of_origin: list[str] = field(
        default_factory=list
    )

    citizenships: list[str] = field(
        default_factory=list
    )

    religion: Optional[CodeableConcept] = None

    communications: list[PatientCommunication] = field(
        default_factory=list
    )

    contacts: list[PatientContact] = field(
        default_factory=list
    )