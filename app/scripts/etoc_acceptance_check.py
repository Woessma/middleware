#!/usr/bin/env python3
"""Server-based acceptance check for CH eTOC document conversion.

This script validates the end-to-end baseline against the running middleware and
FHIR server setup:
1. Fetch FHIR CapabilityStatement from /metadata.
2. Build CH eTOC document bundle via /cda/etoc/convert.
3. Check basic CH eTOC document invariants.
4. Run FHIR server $validate on the produced Bundle.
5. Optionally persist the bundle with POST /fhir (disabled by default).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests


DEFAULT_CDA_SAMPLE = "app/tests/data/CDA-EPIC.xml"
DEFAULT_MIDDLEWARE_URL = "http://localhost:8000"
DEFAULT_FHIR_URL = "http://localhost:8080/fhir"


def _normalize_base(url: str) -> str:
    return url.rstrip("/")


def _make_auth_header(token: str | None) -> dict[str, str]:
    if not token:
        return {}

    return {"Authorization": token}


def _fail(message: str, details: Any | None = None) -> int:
    print(f"[FAIL] {message}")

    if details is not None:
        if isinstance(details, (dict, list)):
            print(json.dumps(details, indent=2, ensure_ascii=True))
        else:
            print(str(details))

    return 1


def _ok(message: str) -> None:
    print(f"[OK] {message}")


def _warn(message: str) -> None:
    print(f"[WARN] {message}")


def _get_capability_statement(
    fhir_base_url: str,
    timeout_seconds: int,
    auth_header: dict[str, str],
) -> dict:
    url = f"{_normalize_base(fhir_base_url)}/metadata"

    response = requests.get(
        url,
        headers={
            "Accept": "application/fhir+json",
            **auth_header,
        },
        timeout=timeout_seconds,
    )

    response.raise_for_status()

    payload = response.json()

    if payload.get("resourceType") != "CapabilityStatement":
        raise ValueError("/metadata response is not a CapabilityStatement")

    return payload


def _build_etoc_bundle(
    middleware_base_url: str,
    cda_path: Path,
    workflow_stage: str,
    target: str,
    timeout_seconds: int,
    auth_header: dict[str, str],
) -> dict:
    url = f"{_normalize_base(middleware_base_url)}/cda/etoc/convert"

    with cda_path.open("rb") as cda_file:
        response = requests.post(
            url,
            params={
                "workflow_stage": workflow_stage,
                "target": target,
            },
            files={
                "file": (cda_path.name, cda_file, "application/xml"),
            },
            headers={
                "Accept": "application/json",
                **auth_header,
            },
            timeout=timeout_seconds,
        )

    response.raise_for_status()

    return response.json()


def _assert_etoc_document_shape(bundle: dict) -> None:
    if bundle.get("resourceType") != "Bundle":
        raise ValueError("Converted payload is not a Bundle")

    if bundle.get("type") != "document":
        raise ValueError("Bundle.type must be 'document'")

    entries = bundle.get("entry") or []

    if not entries:
        raise ValueError("Bundle.entry is empty")

    first_resource = (entries[0].get("resource") or {})

    if first_resource.get("resourceType") != "Composition":
        raise ValueError("First entry resource must be Composition")

    profile_urls = ((bundle.get("meta") or {}).get("profile") or [])

    if "http://fhir.ch/ig/ch-etoc/StructureDefinition/ch-etoc-document" not in profile_urls:
        raise ValueError("Bundle is missing CH eTOC document profile")

    composition_profiles = ((first_resource.get("meta") or {}).get("profile") or [])

    if "http://fhir.ch/ig/ch-etoc/StructureDefinition/ch-etoc-composition" not in composition_profiles:
        raise ValueError("Composition is missing CH eTOC composition profile")


def _validate_bundle_on_server(
    fhir_base_url: str,
    bundle: dict,
    timeout_seconds: int,
    auth_header: dict[str, str],
) -> tuple[bool, dict]:
    url = f"{_normalize_base(fhir_base_url)}/Bundle/$validate"

    response = requests.post(
        url,
        json=bundle,
        headers={
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json",
            **auth_header,
        },
        timeout=timeout_seconds,
    )

    response.raise_for_status()

    payload = response.json()

    if payload.get("resourceType") != "OperationOutcome":
        raise ValueError("$validate did not return OperationOutcome")

    issues = payload.get("issue") or []

    has_error = any(issue.get("severity") in {"error", "fatal"} for issue in issues)

    return (not has_error), payload


def _optional_persist_bundle(
    fhir_base_url: str,
    bundle: dict,
    timeout_seconds: int,
    auth_header: dict[str, str],
) -> dict:
    url = _normalize_base(fhir_base_url)

    response = requests.post(
        url,
        json=bundle,
        headers={
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json",
            **auth_header,
        },
        timeout=timeout_seconds,
    )

    response.raise_for_status()

    try:
        return response.json()
    except Exception:
        return {"text": response.text}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CH eTOC acceptance check against middleware + FHIR server",
    )

    parser.add_argument(
        "--cda-file",
        default=DEFAULT_CDA_SAMPLE,
        help="Path to CDA input file (default: app/tests/data/CDA-EPIC.xml)",
    )

    parser.add_argument(
        "--middleware-url",
        default=os.getenv("MIDDLEWARE_BASE_URL", DEFAULT_MIDDLEWARE_URL),
        help="Middleware base URL (default: env MIDDLEWARE_BASE_URL or http://localhost:8000)",
    )

    parser.add_argument(
        "--fhir-url",
        default=os.getenv("FHIR_BASE_URL", DEFAULT_FHIR_URL),
        help="FHIR base URL (default: env FHIR_BASE_URL or http://localhost:8080/fhir)",
    )

    parser.add_argument(
        "--workflow-stage",
        choices=["initial", "updated", "completed"],
        default="initial",
        help="workflow_stage used when calling /cda/etoc/convert",
    )

    parser.add_argument(
        "--target",
        choices=["default", "sandbox-placer"],
        default="default",
        help="target used when calling /cda/etoc/convert",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="HTTP timeout in seconds (default: 60)",
    )

    parser.add_argument(
        "--middleware-auth",
        default=os.getenv("MIDDLEWARE_AUTH"),
        help="Authorization header value for middleware (e.g. 'Basic ...' or 'Bearer ...')",
    )

    parser.add_argument(
        "--fhir-auth",
        default=os.getenv("FHIR_AUTH"),
        help="Authorization header value for FHIR server (e.g. 'Basic ...' or 'Bearer ...')",
    )

    parser.add_argument(
        "--persist",
        action="store_true",
        help="If set, POST the generated document bundle to the FHIR base endpoint",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cda_path = Path(args.cda_file)

    if not cda_path.exists():
        return _fail("CDA file not found", str(cda_path))

    middleware_auth_header = _make_auth_header(args.middleware_auth)
    fhir_auth_header = _make_auth_header(args.fhir_auth)

    try:
        capability = _get_capability_statement(
            fhir_base_url=args.fhir_url,
            timeout_seconds=args.timeout,
            auth_header=fhir_auth_header,
        )

        fhir_software = (capability.get("software") or {}).get("name") or "unknown"
        _ok(f"FHIR server reachable: CapabilityStatement ({fhir_software})")

        bundle = _build_etoc_bundle(
            middleware_base_url=args.middleware_url,
            cda_path=cda_path,
            workflow_stage=args.workflow_stage,
            target=args.target,
            timeout_seconds=args.timeout,
            auth_header=middleware_auth_header,
        )
        _ok("Middleware conversion /cda/etoc/convert succeeded")

        _assert_etoc_document_shape(bundle)
        _ok("CH eTOC document shape checks passed")

        valid, validation_outcome = _validate_bundle_on_server(
            fhir_base_url=args.fhir_url,
            bundle=bundle,
            timeout_seconds=args.timeout,
            auth_header=fhir_auth_header,
        )

        if not valid:
            return _fail("FHIR $validate returned error/fatal issues", validation_outcome)

        warning_count = sum(
            1 for issue in (validation_outcome.get("issue") or [])
            if issue.get("severity") == "warning"
        )

        if warning_count:
            _warn(f"FHIR $validate passed with {warning_count} warning issue(s)")
        else:
            _ok("FHIR $validate passed without warnings")

        if args.persist:
            response = _optional_persist_bundle(
                fhir_base_url=args.fhir_url,
                bundle=bundle,
                timeout_seconds=args.timeout,
                auth_header=fhir_auth_header,
            )
            _ok("Bundle persisted to FHIR server")
            print(json.dumps(response, indent=2, ensure_ascii=True))
        else:
            _ok("Persist step skipped (use --persist to enable)")

        return 0

    except requests.HTTPError as ex:
        payload = None
        if ex.response is not None:
            try:
                payload = ex.response.json()
            except Exception:
                payload = ex.response.text
        return _fail(f"HTTP error: {ex}", payload)

    except Exception as ex:
        return _fail(f"Unexpected error: {ex}")


if __name__ == "__main__":
    sys.exit(main())
