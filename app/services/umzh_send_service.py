from __future__ import annotations

from typing import Optional

import requests


def _base(base_url: str) -> str:
    return base_url.rstrip("/")


def send_umzh_bundle(
    bundle: dict,
    destination_base_url: str,
    timeout_seconds: int = 60,
    outbound_authorization: Optional[str] = None,
) -> dict:
    if not destination_base_url:
        raise ValueError("destination_base_url is required")

    entries = bundle.get("entry", [])

    headers = {
        "Content-Type": "application/fhir+json",
        "Accept": "application/fhir+json",
    }

    if outbound_authorization:
        headers["Authorization"] = outbound_authorization

    results = []

    for entry in entries:
        resource = entry.get("resource") or {}
        resource_type = resource.get("resourceType")
        resource_id = resource.get("id")

        if not resource_type or not resource_id:
            results.append(
                {
                    "resourceType": resource_type,
                    "id": resource_id,
                    "status": "skipped",
                    "reason": "missing resourceType or id",
                }
            )
            continue

        url = f"{_base(destination_base_url)}/{resource_type}/{resource_id}"

        try:
            response = requests.put(
                url,
                json=resource,
                headers=headers,
                timeout=timeout_seconds,
            )

            try:
                response_payload = response.json()
            except Exception:
                response_payload = response.text

            results.append(
                {
                    "resourceType": resource_type,
                    "id": resource_id,
                    "url": url,
                    "http_status": response.status_code,
                    "ok": response.status_code < 300,
                    "response": response_payload,
                }
            )

        except Exception as ex:
            results.append(
                {
                    "resourceType": resource_type,
                    "id": resource_id,
                    "url": url,
                    "http_status": None,
                    "ok": False,
                    "error": str(ex),
                }
            )

    successful = sum(1 for item in results if item.get("ok") is True)
    failed = sum(1 for item in results if item.get("ok") is False)
    skipped = sum(1 for item in results if item.get("status") == "skipped")

    return {
        "status": "sent" if failed == 0 else "partial-error",
        "destination_base_url": _base(destination_base_url),
        "bundle_entry_count": len(entries),
        "sent_ok_count": successful,
        "failed_count": failed,
        "skipped_count": skipped,
        "results": results,
    }