from dataclasses import dataclass
from typing import Optional


@dataclass
class Organization:
    """
    Fachliches Organisationsobjekt.

    CDA, HL7v2 oder FHIR können darauf mappen.
    """

    identifier_root: Optional[str] = None
    identifier_value: Optional[str] = None

    name: Optional[str] = None

    telecom: Optional[str] = None

    street: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None

    def has_identifier(self) -> bool:
        return bool(
            self.identifier_root and
            self.identifier_value
        )

    def display_name(self) -> str:
        return self.name or "Unknown Organization"
