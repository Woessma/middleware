import logging

from mappers.allergy_mapper import map_allergy_section
from mappers.condition_mapper import map_condition_section
from mappers.immunization_mapper import map_immunization_section
from mappers.medication_mapper import map_medication_section
from mappers.vitalsign_mapper import map_vitalsign_section
from mappers.goal_mapper import map_goal_section
from mappers.procedure_mapper import map_procedure_section
from mappers.lab_mapper import map_lab_section
from mappers.consent_mapper import map_consent_section
from mappers.careteam_mapper import map_careteam_section
from mappers.social_history_mapper import map_social_history_section


logger = logging.getLogger(__name__)
 
SECTION_MAPPERS = {
    "48765-2": map_allergy_section,
    "10160-0": map_medication_section,
    "11450-4": map_condition_section,
    "11348-0": map_condition_section,
    "11369-6": map_immunization_section,
    "10167-5": map_procedure_section,
    "29762-2": map_social_history_section,
    "8716-3": map_vitalsign_section,
    "61146-7": map_goal_section,
    "46264-8": map_procedure_section,
    "30954-2": map_lab_section,
    "42348-3": map_consent_section,
    "85847-2": map_careteam_section
}
 
 
 
def get_section_mapper(section_code):
 
    logger.debug(
        "get_section_mapper called with section_code=%s",
        section_code,
    )
 
    mapper = SECTION_MAPPERS.get(section_code)
 
    logger.debug("mapper found: %s", mapper)
 
    return mapper
 