"""EchoSOS terminology mappings."""

SNOMED_SYSTEM = "http://snomed.info/sct"


def _snomed(code, display):
    return {
        "system": SNOMED_SYSTEM,
        "code": code,
        "display": display,
    }


ECHOSOS_MEDICAL_HISTORY = {
    "Asthma": _snomed("195967001", "Asthma"),
    "Diabetes": _snomed("73211009", "Diabetes mellitus"),
    "Chronisch obstruktive Lungenerkrankung (COPD)": _snomed(
        "13645005", "Chronic obstructive pulmonary disease"
    ),
    "Koronare Herzkrankheit": _snomed("53741008", "Coronary arteriosclerosis"),
    "Herzinsuffizienz": _snomed("84114007", "Heart failure"),
    "Herzrhythmusstörungen": _snomed("698247007", "Cardiac arrhythmia"),
    "Periphere arterielle Verschlusskrankheit": _snomed(
        "399957001", "Peripheral arterial occlusive disease"
    ),
    "Abdominales Aortenaneurysma": _snomed(
        "233985008", "Abdominal aortic aneurysm"
    ),
    "Künstliche Herzklappen": _snomed(
        "737277001", "Prosthetic heart valve in situ"
    ),
    "Störung der Blutgerinnung": _snomed(
        "64779008", "Blood coagulation disorder"
    ),
    "Krampfanfälle": _snomed("91175000", "Seizure"),
    "Nierenversagen/Dialyse": {
        "requires_disambiguation": True,
        "alternatives": (
            _snomed("42399005", "Renal failure syndrome"),
            _snomed("105502003", "Dependence on renal dialysis"),
        ),
    },
    "Leberkrankheit": _snomed("235856003", "Disease of liver"),
    "Ansteckende Krankheit": _snomed("40733004", "Infectious disease"),
    "Herzschrittmacher/Defibrillator": {
        "requires_disambiguation": True,
        "alternatives": (
            _snomed("441509002", "Cardiac pacemaker in situ"),
            _snomed("441769002", "Cardiac defibrillator in situ"),
        ),
    },
    "Schwierige Intubation": _snomed("718447001", "Difficult intubation"),
    "Organtransplantierter": _snomed(
        "161663000", "H/O: tissue/organ recipient"
    ),
}

ECHOSOS_ALLERGENS = {
    "Medikamente": {
        "Penizillin": _snomed("91936005", "Allergy to penicillin"),
        "Andere Antibiotika": _snomed("416098002", "Allergy to drug"),
        "Entzündungshemmer": _snomed(
            "293610009", "Allergy to non-steroidal anti-inflammatory agent"
        ),
        "Aspirin": _snomed("293586001", "Allergy to aspirin"),
        "Kontrastmittel": _snomed("293637006", "Allergy to contrast media"),
        "Curare (Anästhesie)": _snomed(
            "294225008", "Allergy to nondepolarizing agent"
        ),
    },
    "Lebensmittel": {
        "Erdnüsse": _snomed("91935009", "Allergy to peanut"),
        "Nüsse": _snomed("91934008", "Allergy to nut"),
        "Meeresfrüchte": _snomed("91937001", "Allergy to seafood"),
    },
    "Insektengift": {
        "Bienenstich": _snomed("424213003", "Allergy to bee venom"),
        "Wespenstich": _snomed("423058007", "Allergy to wasp venom"),
    },
    "Weitere": {
        "Andere": None,
    },
}

ECHOSOS_ALLERGY_OPTIONS_WITHOUT_CODE = frozenset({"Keine", "Andere"})

ECHOSOS_ALLERGENS_REQUIRING_CONFIRMATION = frozenset({
    "Andere Antibiotika",
    "Entzündungshemmer",
    "Curare (Anästhesie)",
})

ECHOSOS_ALLERGY_REACTIONS = {
    "Hautrötung": _snomed("444827008", "Erythema of skin"),
    "Schwellung der Haut": _snomed("300886007", "Swelling of skin"),
    "Atemnot": _snomed("267036007", "Dyspnea"),
    "Angioödem": _snomed("41291007", "Angioedema"),
    "Anaphylaxie": _snomed("39579001", "Anaphylaxis"),
}