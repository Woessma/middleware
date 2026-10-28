from base64 import urlsafe_b64encode
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey


class JwksConfigurationError(Exception):
    pass


def _base64url_uint(value):
    byte_length = (value.bit_length() + 7) // 8
    encoded = value.to_bytes(byte_length, "big")
    return urlsafe_b64encode(encoded).rstrip(b"=").decode("ascii")


def build_jwks(public_key_path, kid):
    if not kid:
        raise JwksConfigurationError("EPIC_JWKS_KID must not be empty")

    try:
        key_data = Path(public_key_path).read_bytes()
    except OSError as exc:
        raise JwksConfigurationError("Unable to read the configured public key") from exc

    try:
        public_key = serialization.load_pem_public_key(key_data)
    except (TypeError, ValueError) as exc:
        raise JwksConfigurationError("The configured public key is not valid PEM") from exc

    if not isinstance(public_key, RSAPublicKey):
        raise JwksConfigurationError("The configured public key must be RSA")

    numbers = public_key.public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": kid,
                "use": "sig",
                "alg": "RS256",
                "n": _base64url_uint(numbers.n),
                "e": _base64url_uint(numbers.e),
            }
        ]
    }
