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
ZGOPS_HTTP = _load_module("zgops_http_fallback_test", SCRIPT_DIR / "zgops_http.py")
FIND_PROJECT = _load_module("zgops_find_project_fallback_test", SCRIPT_DIR / "find_project.py")


class ZgopsHttpFallbackTests(unittest.TestCase):
    def test_request_with_fallback_uses_curl_after_requests_connection_error(self):
        session = requests.Session()
        session.headers.update({"Accept-Language": "zh"})

        def _fake_run(args, capture_output, text, encoding, timeout, check):
            body_path = args[args.index("-o") + 1]
            Path(body_path).write_text(json.dumps({"result": {"id": 3094}}), encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="200", stderr="")

        with patch.object(session, "request", side_effect=requests.ConnectionError("No route to host")):
            with patch.object(ZGOPS_HTTP.subprocess, "run", side_effect=_fake_run):
                response = ZGOPS_HTTP.request_with_fallback(
                    session,
                    "GET",
                    "http://cmdb.example.com/api/v0.1/ci/3094",
                    timeout=10,
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["id"], 3094)

    def test_cmdb_http_client_falls_back_to_curl_when_opener_fails(self):
        client = FIND_PROJECT.CmdbHttpClient("http://gateway.example.com", "gateway-token")

        def _fake_run(args, capture_output, text, encoding, timeout, check):
            body_path = args[args.index("-o") + 1]
            Path(body_path).write_text(json.dumps({"result": [{"_id": 3094}]}), encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="200", stderr="")

        with patch.object(client.opener, "open", side_effect=OSError("No route to host")):
            with patch.object(FIND_PROJECT.subprocess, "run", side_effect=_fake_run):
                payload = client._request_json("/api/v0.1/ci/3094")

        self.assertEqual(payload["result"][0]["_id"], 3094)

    def test_fetch_with_bearer_returns_gateway_response(self):
        session = requests.Session()
        anonymous_response = ZGOPS_HTTP.FallbackResponse(401, json.dumps({"msg": "unauthorized"}))
        with patch.object(
            ZGOPS_HTTP,
            "request_with_fallback",
            return_value=anonymous_response,
        ) as request_mock:
            response = ZGOPS_HTTP.fetch_with_auth_fallback(
                session,
                base_url="http://gateway.example.com/cmdb",
                path="/api/v0.1/ci/3094",
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(request_mock.call_count, 1)

    def test_cmdb_http_client_does_not_attempt_password_login_after_http_401(self):
        client = FIND_PROJECT.CmdbHttpClient("http://gateway.example.com", "gateway-token")

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
            ],
        ) as request_mock:
            with self.assertRaises(FIND_PROJECT.urllib.error.HTTPError):
                client._request_json("/api/v0.1/ci/3094")

        self.assertEqual(request_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
