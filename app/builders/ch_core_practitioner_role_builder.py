CH_CORE_PRACTITIONER_ROLE_PROFILE = (
    "http://fhir.ch/ig/ch-core/StructureDefinition/"
    "ch-core-practitionerrole"
)

PRACTITIONER_ROLE_IDENTIFIER_SYSTEM = (
    "https://fhir.omnilink.ch/fhir/"
    "NamingSystem/practitionerrole"
)


def build_ch_core_practitioner_role(
    practitioner_id: str,
    organization_id: str,
    *,
    import_key: str | None = None,
) -> dict:

    role_identifier = (
        f"cda-{import_key}" if import_key is not None else
        f"{practitioner_id}-{organization_id}"
    )

    return {
        "resourceType": "PractitionerRole",
        "meta": {
            "profile": [
                CH_CORE_PRACTITIONER_ROLE_PROFILE
            ]
        },
        "identifier": [
            {
                "system": (
                    PRACTITIONER_ROLE_IDENTIFIER_SYSTEM
                ),
                "value": role_identifier,
            }
        ],
        "active": True,
        "practitioner": {
            "reference":
                f"Practitioner/{practitioner_id}"
        },
        "organization": {
            "reference":
                f"Organization/{organization_id}"
        }
    }