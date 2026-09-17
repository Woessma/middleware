"""CH VACD terminology definitions."""

OLD_SWISS_VACCINES = "http://fhir.ch/ig/ch-vacd/CodeSystem/ch-vacd-myvaccines-cs"
SWISSMEDIC_AUTHORIZED_VACCINES = "http://fhir.ch/ig/ch-vacd/CodeSystem/ch-vacd-swissmedic-cs"

VACD = {
    "OLD_SWISS_VACCINES": OLD_SWISS_VACCINES,
    "SWISSMEDIC_AUTHORIZED_VACCINES": SWISSMEDIC_AUTHORIZED_VACCINES,
}

VACD_VACCINES = {
    "COVID_19": {
        "cvx": "207",
        "snomed": "1119349007",
        "swissmedic": "COVID-19",
    },
    "MODERNA": {
        "cvx": "207",
        "snomed": "1119349007",
        "swissmedic": "COVID-19-MODERNA",
    },
    "PFIZER": {
        "cvx": "207",
        "snomed": "1119349007",
        "swissmedic": "COVID-19-PFIZER",
    },
    "PFIZER_COVID_19_IMPFUNG": {
        "cvx": "207",
        "snomed": "1119349007",
        "swissmedic": "COVID-19-PFIZER",
    },
    "INFLUENZA": {
        "cvx": "140",
        "snomed": "346524008",
        "swissmedic": "INFLUENZA",
    },
    "INFLUENZA_IMPFUNG": {
        "cvx": "202",
        "snomed": "346524008",
        "swissmedic": "INFLUENZA",
    },
}
