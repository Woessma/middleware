# app/fhir/references.py

def build_reference(
    resource_type: str,
    resource_id: str
) -> dict:

    return {
        "reference":
            f"{resource_type}/{resource_id}"
    }