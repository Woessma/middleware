import unittest
import json
import io
import zipfile
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from main import FHIR_BASE, app
from services.echosos_service import EchoSosPatientMatchConflictError, parse_echosos_data
from services.fhir_mdm_service import FhirMdmMatchConflictError
from services.pmlc_auth_service import PmlcAuthError


class EchoSosFhirProxyTests(unittest.TestCase):
    def test_mdm_chart_keeps_one_patient_and_includes_confirmed_source_resources(self):
        def chart(path, *_args, **_kwargs):
            patient_id = path.split("/")[1]
            specific = (
                {"resourceType": "Immunization", "id": "v1", "patient": {"reference": "Patient/source"}}
                if patient_id == "source" else
                {"resourceType": "Observation", "id": "o1", "subject": {"reference": "Patient/golden"}}
            )
            resources = [
                {"resourceType": "Patient", "id": patient_id},
                specific,
                {"resourceType": "Practitioner", "id": "shared"},
            ]
            return Mock(status_code=200, body=json.dumps({
                "resourceType": "Bundle", "entry": [{"resource": r} for r in resources],
            }).encode())

        with (
            patch("main.authorize_echosos"),
            patch("main.find_linked_golden_id", return_value="golden"),
            patch("main.find_confirmed_patient_source_ids", return_value=["source"]),
            patch("main._proxy_echosos_fhir_request", side_effect=chart) as lookup,
        ):
            response = self.client.get("/echosos/fhir/Patient/source/$mdm-everything", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        resources = [entry["resource"] for entry in response.json()["entry"]]
        self.assertEqual([(r["resourceType"], r["id"]) for r in resources], [
            ("Patient", "golden"), ("Observation", "o1"), ("Practitioner", "shared"), ("Immunization", "v1"),
        ])
        self.assertEqual(resources[-1]["patient"]["reference"], "Patient/source")
        self.assertEqual([call.args[0] for call in lookup.await_args_list],
                         ["Patient/golden/$everything", "Patient/source/$everything"])

    def test_mdm_chart_rejects_unauthorized_requests_without_reading_links(self):
        with (
            patch("main.authorize_echosos", side_effect=PmlcAuthError(401, "denied")),
            patch("main.find_linked_golden_id") as lookup,
        ):
            response = self.client.get("/echosos/fhir/Patient/golden/$mdm-everything")
        self.assertEqual(response.status_code, 401)
        lookup.assert_not_called()

    def test_poc_notfall_test_page_is_served_separately(self):
        response = self.client.get("/echosos-poc-notfall-test.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("Patientensuche", response.text)
        self.assertIn("Diesen Patienten auswählen", response.text)
        self.assertIn("EchoSOS-Eingabe", response.text)
        self.assertIn("sourceFile", response.text)
        self.assertIn("POC-JSON erzeugen", response.text)

    def test_poc_search_groups_confirmed_matches_but_keeps_unlinked_patients(self):
        demographic_fields = {"name": [{"family": "Beispiel"}], "birthDate": "1980-01-02"}
        upstream = {
            "resourceType": "Bundle",
            "entry": [
                {"resource": {"resourceType": "Patient", "id": pid, **demographic_fields}}
                for pid in ("source", "golden", "unlinked")
            ],
            "link": [{"relation": "next", "url": "https://fhir.example/next"}],
        }
        with (
            patch("main.authorize_echosos"),
            patch("main.find_linked_golden_id", side_effect=["golden", None, None]),
            patch("main._proxy_echosos_fhir_request", return_value=Mock(
                status_code=200, body=json.dumps(upstream).encode(),
            )) as lookup,
        ):
            response = self.client.get(
                "/echosos/poc-notfall-patients",
                params={"family": "Beispiel", "given": "Eva", "birthdate": "1980-01-02"},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "patients": [{"id": pid, **demographic_fields} for pid in ("golden", "unlinked")],
            "truncated": True,
        })
        lookup.assert_awaited_once()

    def test_poc_search_loads_golden_patient_for_source_only_identifier_match(self):
        source = {"resourceType": "Patient", "id": "source"}
        golden = {"resourceType": "Patient", "id": "golden", "gender": "female"}
        with (
            patch("main.authorize_echosos"),
            patch("main.find_linked_golden_id", return_value="golden"),
            patch("main._proxy_echosos_fhir_request", side_effect=[
                Mock(status_code=200, body=json.dumps({
                    "resourceType": "Bundle", "entry": [{"resource": source}],
                }).encode()),
                Mock(status_code=200, body=json.dumps(golden).encode()),
            ]) as lookup,
        ):
            response = self.client.get(
                "/echosos/poc-notfall-patients", params={"identifier": "urn:test|1"}, headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "patients": [{"id": "golden", "gender": "female"}], "truncated": False,
        })
        self.assertEqual([call.args[0] for call in lookup.await_args_list], ["Patient", "Patient/golden"])

    def test_poc_search_does_not_choose_between_conflicting_confirmed_links(self):
        with (
            patch("main.authorize_echosos"),
            patch("main.find_linked_golden_id", side_effect=FhirMdmMatchConflictError("ambiguous")),
            patch("main._proxy_echosos_fhir_request", return_value=Mock(
                status_code=200,
                body=b'{"resourceType":"Bundle","entry":[{"resource":{"resourceType":"Patient","id":"source"}}]}',
            )),
        ):
            response = self.client.get(
                "/echosos/poc-notfall-patients", params={"identifier": "urn:test|1"}, headers=self.headers,
            )
        self.assertEqual(response.status_code, 409)

    def _mock_poc_access(self, golden_id=None, source_ids=()):
        self.enterContext(patch("main.authorize_echosos"))
        self.enterContext(patch("main.find_linked_golden_id", return_value=golden_id))
        self.enterContext(patch("main.find_confirmed_patient_source_ids", return_value=list(source_ids)))

    def test_poc_notfall_rejects_unauthorized_requests_before_searching(self):
        with (
            patch("main.authorize_echosos", side_effect=PmlcAuthError(401, "denied")),
            patch("main._patient_search") as patient_search,
            patch("main.find_linked_golden_id") as mdm_lookup,
        ):
            response = self.client.post(
                "/echosos/poc-notfall-logobject",
                content="https://eid.echosos.com/#b=1&f=Eva&g=fGBP&l=Beispiel",
                headers={"Content-Type": "text/plain"},
            )
        self.assertEqual(response.status_code, 401)
        patient_search.assert_not_called()
        mdm_lookup.assert_not_called()

    @patch("main._patient_search")
    @patch("main._proxy_echosos_fhir_request", new_callable=AsyncMock)
    def test_poc_notfall_logobject_is_created_from_selected_fhir_patient(
        self, everything, patient_search,
    ):
        self._mock_poc_access(golden_id="golden", source_ids=["p1"])
        patient = {
            "resourceType": "Patient",
            "id": "golden",
            "name": [{"given": ["Eva"], "family": "Beispiel"}],
            "birthDate": "1980-01-02",
            "gender": "female",
        }
        def chart(path, *_args, **_kwargs):
            resources = [patient] if path.startswith("Patient/golden/") else [
                {"resourceType": "Patient", "id": "p1"},
                {
                    "resourceType": "Condition",
                    "id": "condition",
                    "subject": {"reference": "Patient/p1"},
                    "code": {"coding": [{"display": "Asthma"}]},
                },
            ]
            return Mock(status_code=200, body=json.dumps({
                "resourceType": "Bundle",
                "entry": [{"resource": r} for r in resources],
            }).encode())
        everything.side_effect = chart

        with patch("main.requests.post") as post, patch("main.requests.put") as put:
            response = self.client.post(
                "/echosos/poc-notfall-logobject",
                json={"patientId": "p1"},
                headers=self.headers,
            )
        post.assert_not_called()
        put.assert_not_called()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["personal"]["firstName"], "Eva")
        self.assertEqual(data["personal"]["lastName"], "Beispiel")
        self.assertEqual(data["personal"]["dateOfBirth"], "1980-01-02")
        self.assertEqual(data["personal"]["sex"], "W")
        self.assertEqual(data["medical"]["preExistingConditions"], ["Asthma"])
        patient_search.assert_not_called()
        self.assertEqual([call.args[0] for call in everything.await_args_list],
                         ["Patient/golden/$everything", "Patient/p1/$everything"])

    @patch("main._proxy_echosos_fhir_request", new_callable=AsyncMock)
    def test_poc_notfall_logobject_rejects_invalid_selected_patient_id(self, everything):
        self._mock_poc_access()
        response = self.client.post(
            "/echosos/poc-notfall-logobject",
            json={"patientId": "../Observation/1"},
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 400)
        everything.assert_not_awaited()

    @patch("main._proxy_echosos_fhir_request", new_callable=AsyncMock)
    def test_poc_notfall_logobject_rejects_bundle_without_selected_patient(self, everything):
        self._mock_poc_access(golden_id="golden", source_ids=["p1"])
        everything.side_effect = [
            Mock(status_code=200, body=b'{"resourceType":"Bundle","entry":[{"resource":{"resourceType":"Patient","id":"golden"}}]}'),
            Mock(status_code=200, body=b'{"resourceType":"Bundle","entry":[]}'),
        ]

        response = self.client.post(
            "/echosos/poc-notfall-logobject",
            json={"patientId": "p1"},
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 502)
        self.assertIn("nicht vollständig", response.json()["detail"])

    def test_poc_notfall_qr_review_requires_bound_confirmation_and_preserves_scan_data(self):
        path = "/echosos/poc-notfall-logobject"
        url = "https://eid.echosos.com/#b=1&f=Eva&g=fGBP&l=Beispiel"
        headers = {**self.headers, "Content-Type": "text/plain"}
        candidates = {"golden": {"patientId": "golden", "name": "Eva Beispiel"}}
        chart = {"entry": [
            {"resource": {"resourceType": "Patient", "id": "golden", "gender": "female"}},
        ]}
        with (
            patch("main.authorize_echosos", return_value={"iss": "issuer", "sub": "reviewer", "azp": "client"}),
            patch("main._patient_search", side_effect=EchoSosPatientMatchConflictError("ambiguous")),
            patch("services.echosos_review_service._candidates", return_value=candidates),
            patch("main._load_echosos_mdm_chart", return_value=chart) as mdm_lookup,
            patch("main.requests.post") as post,
            patch("main.requests.put") as put,
        ):
            review = self.client.post(path, content=url, headers=headers)
            self.assertEqual(review.status_code, 409)
            self.assertEqual(review.json()["code"], "patient_review_required")
            self.assertEqual(review.json()["candidates"], list(candidates.values()))
            confirmation = {
                **headers,
                "X-EchoSOS-Review-ID": review.json()["reviewId"],
                "X-EchoSOS-Patient-ID": "golden",
                "X-EchoSOS-Identity-Verified": "true",
            }
            unverified = self.client.post(path, content=url, headers={
                **confirmation, "X-EchoSOS-Identity-Verified": "false",
            })
            self.assertEqual(unverified.status_code, 400)
            wrong_scan = self.client.post(path, content=url.replace("Eva", "Anne"), headers=confirmation)
            self.assertEqual(wrong_scan.status_code, 409)
            mdm_lookup.assert_not_awaited()

            confirmed = self.client.post(path, content=url, headers=confirmation)
            self.assertEqual(confirmed.status_code, 200)
            self.assertEqual(confirmed.json()["personal"]["firstName"], "Eva")
            self.assertEqual(confirmed.json()["personal"]["sex"], "W")
            replay = self.client.post(path, content=url, headers=confirmation)
            self.assertEqual(replay.status_code, 409)
            mdm_lookup.assert_awaited_once()
            self.assertEqual(mdm_lookup.await_args.args[0], "golden")
            post.assert_not_called()
            put.assert_not_called()

    @patch("main._patient_search", return_value=None)
    def test_poc_notfall_logobject_endpoint_returns_target_json_without_fhir_match(
        self, _patient_search,
    ):
        self._mock_poc_access()
        url = (
            "https://eid.echosos.com/#b=1&f=Eva&g=fGBP&l=Beispiel"
            "&n1=Max%20Beispiel&p1=%2B41000000000"
        )

        with (
            patch("main.requests.post") as post,
            patch("main.requests.put") as put,
        ):
            response = self.client.post(
                "/echosos/poc-notfall-logobject",
                content=url.encode(),
                headers={**self.headers, "Content-Type": "text/plain"},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            set(data),
            {
                "createdAt",
                "personal",
                "emergencyContacts",
                "medical",
                "implants",
                "provision",
            },
        )
        self.assertEqual(data["personal"]["firstName"], "Eva")
        self.assertEqual(data["emergencyContacts"][0]["lastName"], "Beispiel")
        self.assertIsNone(data["personal"]["sex"])
        post.assert_not_called()
        put.assert_not_called()

    @patch("main._proxy_echosos_fhir_request", new_callable=AsyncMock)
    @patch("main._patient_search")
    def test_poc_notfall_logobject_endpoint_enriches_from_fhir(
        self, patient_search, everything,
    ):
        self._mock_poc_access()
        patient = {
            "resourceType": "Patient",
            "id": "p1",
            "gender": "female",
        }
        patient_search.return_value = patient
        everything.return_value = Mock(
            status_code=200,
            body=json.dumps({
                "resourceType": "Bundle",
                "entry": [
                    {"resource": patient},
                    {"resource": {
                        "resourceType": "Condition",
                        "id": "condition",
                        "code": {
                            "coding": [{"code": "195967001", "display": "Asthma"}],
                            "text": "Asthma",
                        },
                    }},
                ],
            }).encode(),
        )
        url = (
            "https://eid.echosos.com/#b=1&f=Eva&g=fGBP&l=Beispiel"
        )

        with (
            patch("main.requests.post") as post,
            patch("main.requests.put") as put,
        ):
            response = self.client.post(
                "/echosos/poc-notfall-logobject",
                content=url.encode(),
                headers={**self.headers, "Content-Type": "text/plain"},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["personal"]["sex"], "W")
        self.assertEqual(data["medical"]["preExistingConditions"], ["Asthma"])
        everything.assert_awaited_once()
        self.assertEqual(everything.call_args.args[0], "Patient/p1/$everything")
        self.assertEqual(everything.call_args.kwargs["query_params"], [("_count", "500")])
        post.assert_not_called()
        put.assert_not_called()

    def test_preview_decodes_all_fields_without_network_or_fhir_writes(self):
        url = (
            "https://eid.echosos.com/#a=BHKL&b=1&d=BS&f=Max&g=fGBP&l=Beispiel"
            "&m=BG&n1=Kontakt%201&p1=%2B41000000001"
            "&n2=Kontakt%202&p2=%2B41000000002"
            "&n3=Kontakt%203&p3=%2B41000000003&o=0&s=0&r=ACAE"
            "&i=Freitext%20%3Ctest%3E&custom=unbekannt"
        )
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as pkpass:
            pkpass.writestr("pass.json", json.dumps({"barcodes": [{"message": url}]}))
        with (
            patch("main.requests.get") as get,
            patch("main.requests.post") as post,
            patch("main.requests.put") as put,
        ):
            for body, content_type in (
                (url.encode(), "text/plain; charset=utf-8"),
                (archive.getvalue(), "application/vnd.apple.pkpass"),
            ):
                response = self.client.post(
                    "/echosos/preview", content=body,
                    headers={**self.headers, "Content-Type": content_type},
                )
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data, parse_echosos_data(url))
                self.assertEqual(len(data["emergency_contacts"]), 3)
                self.assertEqual(len(data["allergy_selections"]), 4)
                self.assertEqual(data["medical_history_selections"], ["Asthma", "Diabetes"])
                self.assertEqual(data["medication_selections"], ["Antihypertensiva", "Antidepressiva"])
                self.assertEqual(data["other_information"], "Freitext <test>")
            get.assert_not_called()
            post.assert_not_called()
            put.assert_not_called()

    def test_preview_rejects_missing_auth_empty_or_invalid_payload(self):
        response = self.client.post("/echosos/preview", content=b"anything")
        self.assertEqual(response.status_code, 401)
        for body in (b"", b"https://example.org/#f=Test", b"not an image"):
            response = self.client.post(
                "/echosos/preview", content=body, headers=self.headers,
            )
            self.assertEqual(response.status_code, 400)

    def setUp(self):
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer test-token"}

    @patch("main.requests.post")
    def test_proxies_echo_import_body_and_authentication(self, mock_post):
        upstream = Mock()
        upstream.status_code = 200
        upstream.content = b'{"resourceType":"Bundle","type":"transaction-response"}'
        upstream.headers = {"Content-Type": "application/json;charset=utf-8"}
        mock_post.return_value = upstream
        body = b"----boundary\r\npayload\r\n----boundary--\r\n"
        content_type = "multipart/form-data; boundary=boundary"

        response = self.client.post(
            "/echosos/import",
            content=body,
            headers={
                **self.headers,
                "Content-Type": content_type,
                "Accept": "application/json",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, upstream.content)
        self.assertEqual(
            response.headers["content-type"],
            "application/json;charset=utf-8",
        )
        mock_post.assert_called_once_with(
            "https://api.omnilink.ch/v1/echosos/resolve",
            data=body,
            headers={
                "Authorization": "Bearer test-token",
                "Accept": "application/json",
                "Content-Type": content_type,
            },
            timeout=300,
        )

    @patch("main.requests.post")
    def test_forwards_raw_camera_and_file_bodies_unchanged(self, mock_post):
        upstream = Mock()
        upstream.status_code = 200
        upstream.content = b'{"resourceType":"Bundle","type":"transaction-response"}'
        upstream.headers = {"Content-Type": "application/json"}
        mock_post.return_value = upstream

        for body, content_type in (
            (
                b"https://eid.echosos.com/#f=Test&l=Beispiel&g=fGBP",
                "text/plain; charset=utf-8",
            ),
            (b"\x89PNG\r\n\x1a\nsynthetic", "image/png"),
            (b"PKsynthetic", "application/vnd.apple.pkpass"),
        ):
            with self.subTest(content_type=content_type):
                response = self.client.post(
                    "/echosos/import",
                    content=body,
                    headers={
                        **self.headers,
                        "Content-Type": content_type,
                        "Accept": "application/json",
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(mock_post.call_args.kwargs["data"], body)
                self.assertEqual(
                    mock_post.call_args.kwargs["headers"]["Content-Type"],
                    content_type,
                )

    @patch("main.requests.post")
    def test_rejects_echo_import_without_bearer_token(self, mock_post):
        response = self.client.post("/echosos/import", content=b"payload")

        self.assertEqual(response.status_code, 401)
        mock_post.assert_not_called()

    @patch("main.requests.get")
    def test_proxies_patient_everything_query_with_auth_and_query_parameters(
        self,
        mock_get,
    ):
        upstream = Mock()
        upstream.status_code = 200
        upstream.content = b'{"resourceType":"Bundle","entry":[]}'
        upstream.headers = {"Content-Type": "application/fhir+json"}
        mock_get.return_value = upstream

        response = self.client.get(
            "/echosos/fhir/Patient/123/$everything?_count=500",
            headers={
                **self.headers,
                "Accept": "application/fhir+json, application/json",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, upstream.content)
        self.assertEqual(response.headers["content-type"], "application/fhir+json")
        mock_get.assert_called_once_with(
            f"{FHIR_BASE.rstrip('/')}/Patient/123/$everything",
            params=[("_count", "500")],
            headers={
                "Accept": "application/fhir+json, application/json",
                "Authorization": "Bearer test-token",
            },
            timeout=30,
        )

    @patch("main.requests.get")
    def test_everything_combines_all_pages_without_filtering_resource_types(self, mock_get):
        next_url = f"{FHIR_BASE.rstrip('/')}?_getpages=synthetic&_getpagesoffset=500"
        pages = [
            {
                "resourceType": "Bundle",
                "type": "searchset",
                "entry": [{"resource": {"resourceType": "Patient", "id": "123"}}] + [
                    {"resource": {"resourceType": "Observation", "id": str(index)}}
                    for index in range(499)
                ],
                "link": [{"relation": "next", "url": next_url}],
            },
            {
                "resourceType": "Bundle",
                "type": "searchset",
                "entry": [
                    {"resource": {"resourceType": resource_type, "id": str(index)}}
                    for index, resource_type in enumerate(
                        ["Encounter", "Composition", "CareTeam", "Observation"]
                    )
                ],
            },
        ]
        mock_get.side_effect = [
            Mock(status_code=200, content=json.dumps(page).encode())
            for page in pages
        ]

        response = self.client.get(
            "/echosos/fhir/Patient/123/$everything?_count=500", headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["entry"]), 504)
        self.assertEqual(response.json()["link"], [])
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_get.call_args.args, (next_url,))
        self.assertEqual(mock_get.call_args.kwargs["headers"]["Authorization"], self.headers["Authorization"])
        self.assertFalse(mock_get.call_args.kwargs["allow_redirects"])

    @patch("main.requests.get")
    def test_everything_rejects_unsafe_or_cyclic_pagination(self, mock_get):
        for next_url in (
            "https://example.org/fhir?_getpages=foreign",
            f"{FHIR_BASE.rstrip('/')}/Observation",
            f"{FHIR_BASE.rstrip('/')}?_getpages=cycle",
        ):
            with self.subTest(next_url=next_url):
                page = {
                    "resourceType": "Bundle", "entry": [],
                    "link": [{"relation": "next", "url": next_url}],
                }
                mock_get.reset_mock()
                mock_get.side_effect = None
                mock_get.return_value = Mock(status_code=200, content=json.dumps(page).encode())
                response = self.client.get(
                    "/echosos/fhir/Patient/123/$everything?_count=500", headers=self.headers,
                )
                self.assertEqual(response.status_code, 502)
                self.assertLessEqual(mock_get.call_count, 2)

    @patch("main.requests.get")
    def test_everything_does_not_report_partial_results_as_success(self, mock_get):
        first = {
            "resourceType": "Bundle", "entry": [],
            "link": [{"relation": "next", "url": f"{FHIR_BASE.rstrip('/')}?_getpages=test"}],
        }
        for next_page in (
            Mock(status_code=500, content=b"unavailable"),
            Mock(status_code=200, content=b'{"resourceType":"OperationOutcome"}'),
            Mock(status_code=200, content=b"not JSON"),
            Mock(status_code=302, content=b"redirect"),
            Mock(status_code=200, content=b'{"resourceType":"Bundle","link":["invalid"]}'),
            Mock(status_code=200, content=b'{"resourceType":"Bundle","entry":null}'),
        ):
            with self.subTest(next_page=next_page):
                mock_get.side_effect = [
                    Mock(status_code=200, content=json.dumps(first).encode()), next_page,
                ]
                response = self.client.get(
                    "/echosos/fhir/Patient/123/$everything?_count=500", headers=self.headers,
                )
                self.assertEqual(response.status_code, 502)
                self.assertIn("unvollständig", response.json()["detail"])

    @patch("main.requests.get")
    def test_rejects_requests_without_bearer_token(self, mock_get):
        response = self.client.get("/echosos/fhir/Patient/123/$everything")

        self.assertEqual(response.status_code, 401)
        mock_get.assert_not_called()

    @patch("main.requests.get")
    def test_rejects_non_patient_fhir_paths(self, mock_get):
        response = self.client.get(
            "/echosos/fhir/Observation/123",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 404)
        mock_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
