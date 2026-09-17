import logging
from domain.encounter import EncounterData


logger = logging.getLogger(__name__)

NS = {
    "hl7": "urn:hl7-org:v3"
}


STATUS_MAP = {
    "completed": "finished",
    "normal": "finished",
}


def _build_encounter_from_node(node):
    encounter_id = None

    id_node = node.find(
        "hl7:id",
        NS,
    )

    if id_node is not None:
        encounter_id = id_node.get(
            "extension"
        )

    if not encounter_id:
        return None

    status = "finished"

    status_node = node.find(
        "hl7:statusCode",
        NS,
    )

    if status_node is not None:

        status = STATUS_MAP.get(
            status_node.get("code"),
            "finished",
        )

    encounter_class = "AMB"

    class_node = node.find(
        "hl7:code",
        NS,
    )

    if class_node is not None:

        encounter_class = (
            class_node.get("code")
            or "AMB"
        )

    start = None
    end = None

    effective_time = node.find(
        "hl7:effectiveTime",
        NS,
    )

    if effective_time is not None:

        low = effective_time.find(
            "hl7:low",
            NS,
        )

        high = effective_time.find(
            "hl7:high",
            NS,
        )

        if low is not None:
            start = low.get(
                "value"
            )

        if high is not None:
            end = high.get(
                "value"
            )

    return EncounterData(
        encounter_id=encounter_id,
        status=status,
        encounter_class=encounter_class,
        start=start,
        end=end,
    )


def parse_encounters(root):

    encounters = []

    # Encounters aus der Kontakte-Sektion
    encounter_nodes = root.findall(
        ".//hl7:section/hl7:entry/hl7:encounter",
        NS,
    )

    for node in encounter_nodes:
        encounter = _build_encounter_from_node(node)

        if encounter is None:
            continue

        encounters.append(encounter)

        logger.debug(
            "Encounter parsed: %s | %s | %s",
            encounter.encounter_id,
            encounter.encounter_class,
            encounter.status,
        )

    if not encounters:
        encompassing_encounter = root.find(
            ".//hl7:componentOf/hl7:encompassingEncounter",
            NS,
        )

        if encompassing_encounter is not None:
            encounter = _build_encounter_from_node(
                encompassing_encounter
            )

            if encounter is not None:
                encounters.append(encounter)

                logger.debug(
                    "Encounter parsed from encompassingEncounter: %s | %s | %s",
                    encounter.encounter_id,
                    encounter.encounter_class,
                    encounter.status,
                )

    logger.debug(
        "Total encounters parsed: %s",
        len(encounters),
    )

    return encounters