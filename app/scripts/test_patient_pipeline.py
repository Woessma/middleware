import logging
import json
import xml.etree.ElementTree as ET

from pathlib import Path

from parser.cda.patient_parser import parse_patient
from builders.ch_core_patient_builder import (
    build_ch_core_patient
)


logger = logging.getLogger(__name__)


def main():

    logging.basicConfig(level=logging.INFO)

    xml_file = (
        Path(__file__).resolve().parent.parent
        / "tests"
        / "data"
        / "CCDA-LUKSTST-20260105.xml"
    )

    root = ET.parse(xml_file).getroot()

    patient = parse_patient(root)

    logger.info("=== PatientData ===")
    logger.info("%s", patient)

    fhir_patient = build_ch_core_patient(
        patient
    )

    logger.info("=== CH Core Patient ===")
    logger.info(
        "%s",
        json.dumps(
            fhir_patient,
            indent=2,
            ensure_ascii=False
        )
    )

    logger.info("Pipeline successful")


if __name__ == "__main__":
    main()