from dataclasses import dataclass


@dataclass
class EncounterData:
    encounter_id: str | None
    status: str
    encounter_class: str
    start: str | None
    end: str | None