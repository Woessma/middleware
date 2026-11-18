"""CVX terminology definitions."""

from pathlib import Path

SYSTEM = "http://hl7.org/fhir/sid/cvx"
SOURCE_URL = (
    "https://www2a.cdc.gov/vaccines/iis/iisstandards/downloads/CVX.txt"
)

CVX = {
    "COVID_19_ASTRAZENECA": "210",
    "COVID_19_JANSSEN": "212",
    "DTP": "20",
}


def _load_cvx_codes() -> dict[str, dict[str, str | bool]]:
    source_path = Path(__file__).with_name("data") / "CVX.txt"
    codes = {}

    with source_path.open(encoding="utf-8-sig") as source_file:
        for line_number, line in enumerate(source_file, start=1):
            fields = line.rstrip("\r\n").split("|")
            if len(fields) != 7:
                raise ValueError(
                    f"Malformed CDC CVX record on line {line_number}"
                )

            code, short_description, display, notes, status, non_us, updated = (
                field.strip() for field in fields
            )
            if not code:
                continue
            if non_us.lower() not in {"true", "false"}:
                raise ValueError(
                    f"Malformed CDC CVX Non-US flag on line {line_number}"
                )
            if code in codes:
                raise ValueError(f"Duplicate CDC CVX code {code!r}")

            codes[code] = {
                "short_description": short_description,
                "display": display,
                "notes": notes,
                "status": status,
                "non_us": non_us.lower() == "true",
                "last_updated": updated,
            }

    return codes


CVX_CODES = _load_cvx_codes()

CVX_VACCINES = {
    "COVID_19": {
        "snomed": "1119349007",
    },
    "COVID_19_MODERNA": {
        "snomed": "1119349007",
    },
    "COVID_19_PFIZER": {
        "snomed": "1119349007",
    },
    "PFIZER_COVID_19_IMPFUNG": {
        "snomed": "1119349007",
    },
    "INFLUENZA_IMPFUNG": {
        "snomed": "346524008",
    },
    # Display-based antigen-level mappings for Epic exports whose CVX codes are
    # not CDC-conform (Epic sends 184 as "FSME" and 167 as "Diphtherie, Tetanus",
    # while CDC defines 184 = yellow fever and 167 = meningococcal). Mapping by
    # display avoids importing the wrong CDC semantics.
    "FSME": {
        "snomed": "836403007",
    },
    "DIPHTHERIE_TETANUS": {
        "snomed": "871826000",
    },
}


# Curated CVX-to-SNOMED mappings only; do not infer product codes from names.
# Do NOT add Epic's 167/184 here: their CDC meanings (meningococcal/yellow fever)
# contradict the Epic displays (Diphtherie-Tetanus/FSME); those are mapped via
# the display-based CVX_VACCINES entries above instead.
CVX_TO_SNOMED = {
    "207": "1119349007",
    "140": "346524008",
    "202": "346524008",
}


def cvx_concept_for_code(cvx_code: str) -> dict[str, str | bool] | None:
    return CVX_CODES.get(str(cvx_code).strip())


def snomed_code_for_cvx(cvx_code: str) -> str | None:
    return CVX_TO_SNOMED.get(str(cvx_code).strip())
