"""LOINC terminology definitions."""

LOINC = {
    "48765-2": {
        "display": "Allergien",
        "category": "clinical-section"
    },
    "10160-0": {
        "display": "Medikationen",
        "category": "clinical-section"
    },
    "11450-4": {
        "display": "Diagnosen",
        "category": "clinical-section"
    },
    "11369-6": {
        "display": "Impfungen",
        "category": "clinical-section"
    },
    "8716-3": {
        "display": "Vitalwerte",
        "category": "clinical-section"
    },
    "61146-7": {
        "display": "Ziele",
        "category": "clinical-section"
    },
    "46264-8": {
        "display": "Prozeduren",
        "category": "clinical-section"
    },
    "30954-2": {
        "display": "Labor",
        "category": "clinical-section"
    },
    "42348-3": {
        "display": "Einwilligungen",
        "category": "clinical-section"
    },
    "85847-2": {
        "display": "CareTeam",
        "category": "clinical-section"
    },
    "8302-2": {
        "display": "Körpergröße",
        "category": "vital-signs"
    },
    "29463-7": {
        "display": "Körpergewicht",
        "category": "vital-signs"
    },
    "39156-5": {
        "display": "BMI",
        "category": "vital-signs"
    },
    "8480-6": {
        "display": "Systolischer Blutdruck",
        "category": "vital-signs"
    },
    "8462-4": {
        "display": "Diastolischer Blutdruck",
        "category": "vital-signs"
    },
    "8867-4": {
        "display": "Puls",
        "category": "vital-signs"
    },
    "8310-5": {
        "display": "Körpertemperatur",
        "category": "vital-signs"
    }
}


def get_loinc_display(code):
    item = LOINC.get(code)
    return item.get("display") if item else code
