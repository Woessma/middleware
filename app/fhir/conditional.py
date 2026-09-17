# app/fhir/conditional.py

import urllib.parse


def build_conditional_create_url(
    resource_type: str,
    identifier: dict
) -> str:

    system = urllib.parse.quote(
        identifier["system"],
        safe=""
    )

    value = urllib.parse.quote(
        identifier["value"],
        safe=""
    )

    return (
        f"{resource_type}"
        f"?identifier={system}|{value}"
    )
