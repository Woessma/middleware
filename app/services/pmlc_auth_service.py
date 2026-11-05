"""Verify Keycloak access tokens before reading server-side patient data."""

import threading
import time
from urllib.parse import urlsplit

import jwt
import requests

from config import (
    PMLC_KEYCLOAK_ALLOWED_CLIENTS, PMLC_KEYCLOAK_AUDIENCE,
    PMLC_KEYCLOAK_ISSUER, PMLC_KEYCLOAK_REQUIRED_ROLE,
)


class PmlcAuthError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


_lock = threading.Lock()
_cached_keys = []
_cached_issuer = None
_expires = 0


def _signing_key(kid, issuer):
    global _cached_keys, _cached_issuer, _expires
    with _lock:
        if _cached_issuer != issuer or time.monotonic() >= _expires:
            try:
                response = requests.get(
                    f"{issuer}/protocol/openid-connect/certs",
                    headers={"Accept": "application/json"}, timeout=(5, 10),
                    allow_redirects=False,
                )
            except requests.RequestException as ex:
                raise PmlcAuthError(502, "Keycloak signing keys unavailable") from ex
            if response.status_code != 200:
                raise PmlcAuthError(502, "Keycloak signing keys unavailable")
            try:
                body = response.json()
            except ValueError as ex:
                raise PmlcAuthError(502, "Invalid Keycloak signing-key response") from ex
            keys = body.get("keys") if isinstance(body, dict) else None
            if not isinstance(keys, list) or not keys or any(not isinstance(key, dict) for key in keys):
                raise PmlcAuthError(502, "Invalid Keycloak signing-key response")
            _cached_keys, _cached_issuer, _expires = keys, issuer, time.monotonic() + 300
        candidates = [key for key in _cached_keys if key.get("kid") == kid]
        if len(candidates) != 1:
            raise PmlcAuthError(401, "Unknown Keycloak token signing key")
        key = candidates[0]
        if key.get("kty") != "RSA" or key.get("alg", "RS256") != "RS256" \
                or key.get("use", "sig") != "sig":
            raise PmlcAuthError(401, "Unsupported Keycloak token signing key")
        try:
            return jwt.PyJWK.from_dict(key, algorithm="RS256").key
        except (jwt.PyJWTError, ValueError) as ex:
            raise PmlcAuthError(502, "Invalid Keycloak signing key") from ex


def authorize_pmlc(authorization: str) -> None:
    if not isinstance(authorization, str) or not authorization.lower().startswith("bearer ") \
            or not authorization[7:].strip():
        raise PmlcAuthError(401, "A Keycloak Bearer token is required")
    issuer = PMLC_KEYCLOAK_ISSUER.rstrip("/")
    parts = urlsplit(issuer)
    audience = PMLC_KEYCLOAK_AUDIENCE.strip()
    allowed_clients = {client.strip() for client in PMLC_KEYCLOAK_ALLOWED_CLIENTS.split(",") if client.strip()}
    if not (audience or allowed_clients) or parts.scheme != "https" or not parts.netloc \
            or parts.query or parts.fragment or parts.username or parts.password:
        raise PmlcAuthError(503, "PMLC access disabled: configure the Keycloak issuer and API audience or allowed clients")
    token = authorization[7:].strip()
    if len(token) > 16384:
        raise PmlcAuthError(401, "Invalid Keycloak token")
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid or len(kid) > 256:
            raise PmlcAuthError(401, "Invalid Keycloak token")
        claims = jwt.decode(
            token, _signing_key(kid, issuer), algorithms=["RS256"],
            audience=audience or None, issuer=issuer,
            options={
                "require": ["exp", "iat", "iss", "sub"] + (["aud"] if audience else []),
                "verify_aud": bool(audience),
            },
        )
    except jwt.InvalidTokenError as ex:
        raise PmlcAuthError(401, "Invalid or expired Keycloak token") from ex
    if claims.get("typ") != "Bearer":
        raise PmlcAuthError(401, "A Keycloak access token is required")
    if allowed_clients:
        client = claims.get("azp")
        if not isinstance(client, str) or client not in allowed_clients:
            raise PmlcAuthError(403, "Keycloak client not permitted for PMLC access")
    if PMLC_KEYCLOAK_REQUIRED_ROLE:
        realm_access = claims.get("realm_access")
        roles = realm_access.get("roles") if isinstance(realm_access, dict) else None
        if not isinstance(roles, list) or PMLC_KEYCLOAK_REQUIRED_ROLE not in roles:
            raise PmlcAuthError(403, "Required Keycloak realm role missing")
