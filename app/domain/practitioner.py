from dataclasses import dataclass, field

from domain.patient import (
    Identifier,
    HumanName,
    Address,
    Telecom,
)

@dataclass
class PractitionerData:

    active: bool | None = None

    gender: str | None = None
    birth_date: str | None = None

    gln: str | None = None
    zsr: str | None = None

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