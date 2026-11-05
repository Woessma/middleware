"""CH VACD terminology definitions."""

OLD_SWISS_VACCINES = "http://fhir.ch/ig/ch-vacd/CodeSystem/ch-vacd-myvaccines-cs"
SWISSMEDIC_AUTHORIZED_VACCINES = "http://fhir.ch/ig/ch-vacd/CodeSystem/ch-vacd-swissmedic-cs"

VACD = {
    "OLD_SWISS_VACCINES": OLD_SWISS_VACCINES,
    "SWISSMEDIC_AUTHORIZED_VACCINES": SWISSMEDIC_AUTHORIZED_VACCINES,
}

VACD_VACCINES = {
    "COVID_19": {
        "snomed": "1119349007",
    },
    "MODERNA": {
        "snomed": "1119349007",
    },
    "PFIZER": {
        "snomed": "1119349007",
    },
    "PFIZER_COVID_19_IMPFUNG": {
        "snomed": "1119349007",
    },
    "INFLUENZA": {
        "cvx": "140",
        "snomed": "346524008",
    },
    "INFLUENZA_IMPFUNG": {
        "cvx": "202",
        "snomed": "346524008",
    },
}
