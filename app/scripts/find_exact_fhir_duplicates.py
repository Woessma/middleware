import argparse
import json

from services.fhir_duplicate_service import find_exact_fhir_duplicates


def main():
    parser = argparse.ArgumentParser(
        description="Find exact duplicate FHIR resources in the middleware FHIR server",
    )
    parser.add_argument(
        "--resource-type",
        default="MedicationStatement",
        help="FHIR resource type to scan",
    )
    parser.add_argument(
        "--patient-id",
        default=None,
        help="Optional patient id to restrict the search",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=200,
        help="FHIR page size",
    )
    parser.add_argument(
        "--fhir-base",
        default=None,
        help="FHIR base URL; defaults to app config",
    )

    args = parser.parse_args()

    result = find_exact_fhir_duplicates(
        resource_type=args.resource_type,
        patient_id=args.patient_id,
        fhir_base=args.fhir_base,
        count=args.count,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()