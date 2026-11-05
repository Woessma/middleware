import json
import time
import unittest
from unittest.mock import Mock, patch

import jwt
import requests
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from main import app
from services import pmlc_auth_service as auth
from services.pmlc_service import PmlcSourceError


class PmlcAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.private.public_key()))
        cls.public.update(kid="synthetic", use="sig", alg="RS256")

    def setUp(self):
        self.patches = [
            patch.object(auth, "PMLC_KEYCLOAK_ISSUER", "https://idp.example/realms/test"),
            patch.object(auth, "PMLC_KEYCLOAK_AUDIENCE", "synthetic-api"),
            patch.object(auth, "PMLC_KEYCLOAK_ALLOWED_CLIENTS", ""),
            patch.object(auth, "PMLC_KEYCLOAK_REQUIRED_ROLE", "synthetic-reader"),
            patch.object(auth, "_expires", 0),
            patch.object(auth, "_cached_issuer", None),
            patch.object(auth, "_cached_keys", []),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def token(self, **changes):
        now = int(time.time())
        claims = {"iss": "https://idp.example/realms/test", "aud": "synthetic-api", "sub": "synthetic-user",
                  "iat": now - 5, "exp": now + 120, "typ": "Bearer",
                  "realm_access": {"roles": ["synthetic-reader"]}}
        claims.update(changes)
        return "Bearer " + jwt.encode(claims, self.private, algorithm="RS256", headers={"kid": "synthetic"})

    def key_response(self):
        result = Mock(status_code=200)
        result.json.return_value = {"keys": [self.public]}
        return result

    def test_signature_issuer_audience_expiry_and_role_are_checked(self):
        with patch.object(auth.requests, "get", return_value=self.key_response()) as get:
            auth.authorize_pmlc(self.token())
            auth.authorize_pmlc(self.token())
            self.assertEqual(get.call_count, 1)
            self.assertFalse(get.call_args.kwargs["allow_redirects"])
            for changes in ({"aud": "other"}, {"iss": "https://other.example"}, {"exp": 1},
                            {"typ": "ID"}, {"realm_access": {"roles": []}}):
                with self.subTest(changes=changes), self.assertRaises(auth.PmlcAuthError):
                    auth.authorize_pmlc(self.token(**changes))
            other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            token = jwt.encode({"exp": int(time.time()) + 30}, other_key, algorithm="RS256",
                               headers={"kid": "synthetic"})
            with self.assertRaises(auth.PmlcAuthError):
                auth.authorize_pmlc("Bearer " + token)

    def test_missing_configuration_keys_or_invalid_tokens_fail_closed(self):
        with patch.object(auth.requests, "get") as get:
            for token in ("", "Basic synthetic", "Bearer not-a-jwt"):
                with self.assertRaises(auth.PmlcAuthError):
                    auth.authorize_pmlc(token)
            get.assert_not_called()
        with patch.object(auth, "PMLC_KEYCLOAK_AUDIENCE", ""):
            with self.assertRaises(auth.PmlcAuthError) as error:
                auth.authorize_pmlc(self.token())
            self.assertEqual(error.exception.status_code, 503)
        for response in (Mock(status_code=302), Mock(status_code=500)):
            with patch.object(auth.requests, "get", return_value=response):
                with self.assertRaises(auth.PmlcAuthError) as error:
                    auth.authorize_pmlc(self.token())
                self.assertEqual(error.exception.status_code, 502)
        with patch.object(auth.requests, "get", side_effect=requests.Timeout):
            with self.assertRaises(auth.PmlcAuthError):
                auth.authorize_pmlc(self.token())

    def test_unauthorized_request_never_reads_patient_data(self):
        client = TestClient(app)
        with patch("main.generate_pmlc") as generate:
            result = client.post("/fhir/medications/pmlc/from-server?patient_id=p1")
            self.assertEqual(result.status_code, 401)
            self.assertEqual(result.headers["www-authenticate"], "Bearer")
            generate.assert_not_called()
        with patch.object(auth, "PMLC_KEYCLOAK_AUDIENCE", ""), patch("main.generate_pmlc") as generate:
            result = client.post("/fhir/medications/pmlc/from-server?patient_id=p1",
                                 headers={"Authorization": "Bearer synthetic"})
            self.assertEqual(result.status_code, 503)
            generate.assert_not_called()

    def test_invalid_jwks_returns_controlled_errors(self):
        malformed_key = {"kid": "synthetic", "kty": "RSA", "alg": "RS256", "use": "sig"}
        for body, expected in (
            ([], 502), ({"keys": []}, 502), ({"keys": [None]}, 502),
            ({"keys": [malformed_key]}, 502),
            ({"keys": [self.public, self.public]}, 401),
            ({"keys": [{**self.public, "kid": "unknown"}]}, 401),
            ({"keys": [{**self.public, "use": "enc"}]}, 401),
        ):
            with self.subTest(body=body), patch.object(auth, "_expires", 0):
                result = Mock(status_code=200)
                result.json.return_value = body
                with patch.object(auth.requests, "get", return_value=result):
                    with self.assertRaises(auth.PmlcAuthError) as error:
                        auth.authorize_pmlc(self.token())
                    self.assertEqual(error.exception.status_code, expected)
        result = Mock(status_code=200)
        result.json.side_effect = ValueError("Malformed JSON")
        with patch.object(auth, "_expires", 0), patch.object(auth.requests, "get", return_value=result):
            with self.assertRaises(auth.PmlcAuthError) as error:
                auth.authorize_pmlc(self.token())
            self.assertEqual(error.exception.status_code, 502)

    def test_token_rejection_precedes_all_source_reads(self):
        client = TestClient(app)
        for changes, expected in (
            ({"aud": "other"}, 401), ({"exp": 1}, 401),
            ({"sub": None}, 401), ({"nbf": int(time.time()) + 300}, 401),
            ({"realm_access": {"roles": []}}, 403),
        ):
            with self.subTest(changes=changes), \
                 patch.object(auth.requests, "get", return_value=self.key_response()), \
                 patch("main.generate_pmlc") as generate:
                result = client.post(
                    "/fhir/medications/pmlc/from-server?patient_id=p1",
                    headers={"Authorization": self.token(**changes)},
                )
                self.assertEqual(result.status_code, expected)
                self.assertEqual(result.headers["cache-control"], "no-store")
                self.assertEqual(result.json()["resourceType"], "OperationOutcome")
                generate.assert_not_called()

    def test_existing_workbench_access_token_is_accepted_by_signed_authorized_party(self):
        client = TestClient(app)
        with patch.object(auth, "PMLC_KEYCLOAK_AUDIENCE", ""), \
             patch.object(auth, "PMLC_KEYCLOAK_ALLOWED_CLIENTS", "app-omnilink-cardtest"), \
             patch.object(auth, "PMLC_KEYCLOAK_REQUIRED_ROLE", ""), \
             patch.object(auth.requests, "get", return_value=self.key_response()), \
             patch("main.generate_pmlc", side_effect=PmlcSourceError("Synthetic source unavailable")) as generate:
            response = client.post(
                "/fhir/medications/pmlc/from-server?patient_id=p1",
                headers={"Authorization": self.token(
                    azp="app-omnilink-cardtest", aud="account", realm_access={})},
            )
            self.assertEqual(response.status_code, 422)
            generate.assert_called_once_with("p1", "de-CH", "restricted")

    def test_client_allowlist_rejects_missing_wrong_and_untrusted_claims_before_read(self):
        client = TestClient(app)
        with patch.object(auth, "PMLC_KEYCLOAK_AUDIENCE", ""), \
             patch.object(auth, "PMLC_KEYCLOAK_ALLOWED_CLIENTS", "app-omnilink-cardtest"), \
             patch.object(auth, "PMLC_KEYCLOAK_REQUIRED_ROLE", ""), \
             patch.object(auth.requests, "get", return_value=self.key_response()):
            for claims in (
                {}, {"azp": "other-client"}, {"azp": ["app-omnilink-cardtest"]},
                {"client_id": "app-omnilink-cardtest"},
                {"azp": "other-client", "aud": "app-omnilink-cardtest"},
            ):
                with self.subTest(claims=claims), patch("main.generate_pmlc") as generate:
                    response = client.post(
                        "/fhir/medications/pmlc/from-server?patient_id=p1",
                        headers={"Authorization": self.token(**claims)},
                    )
                    self.assertEqual(response.status_code, 403)
                    generate.assert_not_called()
            for claims in ({"exp": 1}, {"iss": "https://other.example"}, {"typ": "ID"}):
                with self.subTest(claims=claims), self.assertRaises(auth.PmlcAuthError):
                    auth.authorize_pmlc(self.token(azp="app-omnilink-cardtest", **claims))

    def test_configured_audience_is_still_required_in_addition_to_client(self):
        with patch.object(auth, "PMLC_KEYCLOAK_ALLOWED_CLIENTS", "app-omnilink-cardtest"), \
             patch.object(auth.requests, "get", return_value=self.key_response()):
            with self.assertRaises(auth.PmlcAuthError) as error:
                auth.authorize_pmlc(self.token(azp="app-omnilink-cardtest", aud="account"))
            self.assertEqual(error.exception.status_code, 401)
