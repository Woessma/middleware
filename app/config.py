import os


FHIR_BASE = os.getenv("FHIR_BASE", "http://fhir-server:8080/fhir")
TERMINOLOGY_BASE_URL = os.getenv("TERMINOLOGY_BASE_URL", "https://tx.fhir.ch/r4")
TERMINOLOGY_TIMEOUT = int(os.getenv("TERMINOLOGY_TIMEOUT", "30"))
TERMINOLOGY_VALIDATION_MODE = os.getenv("TERMINOLOGY_VALIDATION_MODE", "report").lower()

# CH-VACD reference server (openEHR-based, e.g. Impfdossier CH demo) for the "VACD senden" use case.
VACD_SEND_BASE_URL = os.getenv("VACD_SEND_BASE_URL", "https://vaccination-demo.raly.ch/api/fhir")
VACD_SEND_TIMEOUT = int(os.getenv("VACD_SEND_TIMEOUT", "60"))

# Refdata.ch Partner (GLN) lookup - optional enrichment, disabled unless a key is configured.
REFDATA_BASE_URL = os.getenv(
    "REFDATA_BASE_URL",
    "https://api-int.refdata.ch/stage/partner/2.0/Partner.asmx",
)
REFDATA_API_KEY = os.getenv("REFDATA_API_KEY", "")
REFDATA_TIMEOUT = int(os.getenv("REFDATA_TIMEOUT", "15"))
