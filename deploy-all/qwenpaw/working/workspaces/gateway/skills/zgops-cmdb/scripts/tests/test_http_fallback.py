import importlib.util
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCRIPT_DIR = Path(__file__).resolve().parents[1]
VEOPS_HTTP = _load_module("veops_http_fallback_test", SCRIPT_DIR / "veops_http.py")
FIND_PROJECT = _load_module("veops_find_project_fallback_test", SCRIPT_DIR / "find_project.py")


class VeopsHttpFallbackTests(unittest.TestCase):
    def test_request_with_fallback_uses_curl_after_requests_connection_error(self):
        session = requests.Session()
        session.headers.update({"Accept-Language": "zh"})

        def _fake_run(args, capture_output, text, encoding, timeout, check):
            body_path = args[args.index("-o") + 1]
            Path(body_path).write_text(json.dumps({"result": {"id": 3094}}), encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="200", stderr="")

        with patch.object(session, "request", side_effect=requests.ConnectionError("No route to host")):
            with patch.object(VEOPS_HTTP.subprocess, "run", side_effect=_fake_run):
                response = VEOPS_HTTP.request_with_fallback(
                    session,
                    "GET",
                    "http://cmdb.example.com/api/v0.1/ci/3094",
                    timeout=10,
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["id"], 3094)

    def test_cmdb_http_client_falls_back_to_curl_when_opener_fails(self):
        client = FIND_PROJECT.CmdbHttpClient("http://cmdb.example.com", "", "")

        def _fake_run(args, capture_output, text, encoding, timeout, check):
            body_path = args[args.index("-o") + 1]
            Path(body_path).write_text(json.dumps({"result": [{"_id": 3094}]}), encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="200", stderr="")

        with patch.object(client.opener, "open", side_effect=OSError("No route to host")):
            with patch.object(FIND_PROJECT.subprocess, "run", side_effect=_fake_run):
                payload = client._request_json("/api/v0.1/ci/3094")

        self.assertEqual(payload["result"][0]["_id"], 3094)

    def test_fetch_with_auth_fallback_logs_in_only_after_anonymous_401(self):
        session = requests.Session()
        anonymous_response = VEOPS_HTTP.FallbackResponse(401, json.dumps({"msg": "unauthorized"}))
        authenticated_response = VEOPS_HTTP.FallbackResponse(200, json.dumps({"result": {"id": 3094}}))

        with patch.object(
            VEOPS_HTTP,
            "request_with_fallback",
            side_effect=[anonymous_response, authenticated_response],
        ) as request_mock:
            with patch.object(
                VEOPS_HTTP,
                "try_login",
                return_value={"username": "tester"},
            ) as login_mock:
                response = VEOPS_HTTP.fetch_with_auth_fallback(
                    session,
                    base_url="http://cmdb.example.com",
                    path="/api/v0.1/ci/3094",
                    username="tester",
                    password="secret",
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(request_mock.call_count, 2)
        login_mock.assert_called_once()

    def test_cmdb_http_client_logs_in_only_after_anonymous_http_401(self):
        client = FIND_PROJECT.CmdbHttpClient("http://cmdb.example.com", "tester", "secret")

        with patch.object(
            client,
            "_request_json_once",
            side_effect=[
                FIND_PROJECT.urllib.error.HTTPError(
                    url="http://cmdb.example.com/api/v0.1/ci/3094",
                    code=401,
                    msg="unauthorized",
                    hdrs=None,
                    fp=None,
                ),
                {"result": [{"_id": 3094}]},
            ],
        ) as request_mock:
            with patch.object(client, "try_login", return_value=True) as login_mock:
                payload = client._request_json("/api/v0.1/ci/3094")

        self.assertEqual(payload["result"][0]["_id"], 3094)
        self.assertEqual(request_mock.call_count, 2)
        login_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
