import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from main import app


class EpicJwksTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.public_key_path = Path(self.temp_dir.name) / "epic-public.pem"
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public_key_path.write_bytes(
            private_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        self.config = patch.multiple(
            "main",
            EPIC_PUBLIC_KEY_PATH=str(self.public_key_path),
            EPIC_JWKS_KID="epic-key-1",
        )
        self.config.start()
        self.addCleanup(self.config.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def test_publishes_rsa_public_key_as_jwks(self):
        response = self.client.get("/.well-known/jwks.json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertEqual(response.headers["cache-control"], "public, max-age=300")
        jwk = response.json()["keys"][0]
        self.assertEqual(
            {key: jwk[key] for key in ("kty", "kid", "use", "alg", "e")},
            {
                "kty": "RSA",
                "kid": "epic-key-1",
                "use": "sig",
                "alg": "RS256",
                "e": "AQAB",
            },
        )

        modulus_bytes = base64.urlsafe_b64decode(jwk["n"] + "=" * (-len(jwk["n"]) % 4))
        public_key = serialization.load_pem_public_key(self.public_key_path.read_bytes())
        self.assertEqual(
            int.from_bytes(modulus_bytes, "big"),
            public_key.public_numbers().n,
        )

    def test_returns_service_unavailable_when_key_is_missing(self):
        with patch("main.EPIC_PUBLIC_KEY_PATH", ""):
            response = self.client.get("/.well-known/jwks.json")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "JWKS is not configured")

    def test_returns_service_unavailable_for_unreadable_key_file(self):
        with patch("main.EPIC_PUBLIC_KEY_PATH", str(self.public_key_path / "missing.pem")):
            response = self.client.get("/.well-known/jwks.json")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "JWKS public key is unavailable or invalid",
        )


if __name__ == "__main__":
    unittest.main()
