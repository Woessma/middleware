"""CVX terminology definitions."""

SYSTEM = "http://hl7.org/fhir/sid/cvx"

CVX = {
    "COVID_19_ASTRAZENECA": "210",
    "COVID_19_JANSSEN": "212",
    "DTP": "20",
}

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
        "cvx": "202",
        "snomed": "346524008",
    },
    "FSME": {
        "cvx": "184",
    },
}


CVX_TO_SNOMED = {
    "207": "1119349007",
    **{
        vaccine_data["cvx"]: vaccine_data["snomed"]
        for vaccine_data in CVX_VACCINES.values()
        if vaccine_data.get("cvx") and vaccine_data.get("snomed")
    },
}


def snomed_code_for_cvx(cvx_code: str) -> str | None:
    return CVX_TO_SNOMED.get(str(cvx_code).strip())
