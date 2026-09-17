# app/fhir/identifiers.py

def get_cda_identifier_value(
    root: str | None,
    extension: str | None = None
) -> str | None:

    if extension:
        return extension

    return root


def build_cda_identifier(
    root: str,
    extension: str | None = None
) -> dict:

    value = get_cda_identifier_value(
        root,
        extension
    )

    identifier = {
        "system": f"urn:oid:{root}"
    }

    if value:
        identifier["value"] = value

    return identifier