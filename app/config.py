import os


FHIR_BASE = os.getenv("FHIR_BASE", "http://fhir-server:8080/fhir")
HUSKY_VALIDATOR_URL = os.getenv("HUSKY_VALIDATOR_URL", "http://husky-validator:8091")
PMLC_KEYCLOAK_ISSUER = os.getenv(
    "PMLC_KEYCLOAK_ISSUER", "https://idp.omnilink.ch/realms/omnilink"
)
PMLC_KEYCLOAK_AUDIENCE = os.getenv("PMLC_KEYCLOAK_AUDIENCE", "")
PMLC_KEYCLOAK_ALLOWED_CLIENTS = os.getenv("PMLC_KEYCLOAK_ALLOWED_CLIENTS", "app-omnilink-cardtest")
PMLC_KEYCLOAK_REQUIRED_ROLE = os.getenv("PMLC_KEYCLOAK_REQUIRED_ROLE", "")
FHIR_EXTERNAL_BASE_URL = os.getenv("FHIR_EXTERNAL_BASE_URL", "")
FHIR_EXTERNAL_USERNAME = os.getenv("FHIR_EXTERNAL_USERNAME", "")
FHIR_EXTERNAL_PASSWORD = os.getenv("FHIR_EXTERNAL_PASSWORD", "")
FHIR_EXTERNAL_TIMEOUT = int(os.getenv("FHIR_EXTERNAL_TIMEOUT", "5"))
TERMINOLOGY_BASE_URL = os.getenv("TERMINOLOGY_BASE_URL", "https://tx.fhir.ch/r4")
TERMINOLOGY_TIMEOUT = int(os.getenv("TERMINOLOGY_TIMEOUT", "30"))
TERMINOLOGY_VALIDATION_MODE = os.getenv("TERMINOLOGY_VALIDATION_MODE", "report").lower()

# CH-VACD reference server (openEHR-based, e.g. Impfdossier CH demo) for the "VACD senden" use case.
VACD_SEND_BASE_URL = os.getenv("VACD_SEND_BASE_URL", "https://vaccination-demo.raly.ch/api/fhir")
VACD_SEND_TIMEOUT = int(os.getenv("VACD_SEND_TIMEOUT", "60"))
VACD_IMPORT_DB = os.getenv("VACD_IMPORT_DB", "/var/lib/omnilink/vacd/imports.sqlite3")

# Refdata.ch Partner (GLN) lookup - optional enrichment, disabled unless a key is configured.
REFDATA_BASE_URL = os.getenv(
    "REFDATA_BASE_URL",
    "https://api-int.refdata.ch/stage/partner/2.0/Partner.asmx",
)
REFDATA_API_KEY = os.getenv("REFDATA_API_KEY", "")
REFDATA_TIMEOUT = int(os.getenv("REFDATA_TIMEOUT", "15"))

EPIC_PUBLIC_KEY_PATH = os.getenv("EPIC_PUBLIC_KEY_PATH", "")
EPIC_JWKS_KID = os.getenv("EPIC_JWKS_KID", "epic-key-1")
