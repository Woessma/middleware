"""CVX terminology definitions."""

SYSTEM = "http://hl7.org/fhir/sid/cvx"

CVX = {
    "COVID_19_PFIZER": "207",
    "COVID_19_MODERNA": "207",
    "COVID_19_ASTRAZENECA": "210",
    "COVID_19_JANSSEN": "212",
    "DTP": "20",
}

CVX_VACCINES = {
    "COVID_19": {
        "cvx": "207",
        "snomed": "1119349007",
        "swissmedic": "COVID-19",
    },
    "COVID_19_MODERNA": {
        "cvx": "207",
        "snomed": "1119349007",
        "swissmedic": "COVID-19-MODERNA",
    },
    "COVID_19_PFIZER": {
        "cvx": "207",
        "snomed": "1119349007",
        "swissmedic": "COVID-19-PFIZER",
    },
    "PFIZER_COVID_19_IMPFUNG": {
        "cvx": "207",
        "snomed": "1119349007",
        "swissmedic": "COVID-19-PFIZER",
    },
    "INFLUENZA_IMPFUNG": {
        "cvx": "202",
        "snomed": "346524008",
        "swissmedic": "INFLUENZA",
    },
    "FSME": {
        "cvx": "184",
    },
}


CVX_TO_SNOMED = {
    vaccine_data["cvx"]: vaccine_data["snomed"]
    for vaccine_data in CVX_VACCINES.values()
    if vaccine_data.get("cvx") and vaccine_data.get("snomed")
}


def snomed_code_for_cvx(cvx_code: str) -> str | None:
    return CVX_TO_SNOMED.get(str(cvx_code).strip())
