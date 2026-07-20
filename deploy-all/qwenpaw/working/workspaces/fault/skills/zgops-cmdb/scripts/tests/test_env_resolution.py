import importlib.util
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

import requests


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))
FIND_PROJECT = _load_module("zgops_find_project_test", SCRIPT_DIR / "find_project.py")
APP_TOPOLOGY = _load_module("zgops_app_topology_test", SCRIPT_DIR / "app_topology.py")
ZGOPS_HTTP = _load_module("zgops_http_test", SCRIPT_DIR / "zgops_http.py")


class ZgopsCmdbEnvResolutionTests(unittest.TestCase):
    def test_resolve_reads_inoe_env_from_environ(self):
        with patch.dict(
            "os.environ",
            {
                "INOE_API_BASE_URL": "http://gateway.example.com:8080",
                "INOE_API_TOKEN": "gateway-token",
            },
            clear=True,
        ):
            env = FIND_PROJECT._resolve_zgops_env()

        self.assertEqual(
            env,
            {
                "INOE_API_BASE_URL": "http://gateway.example.com:8080",
                "INOE_API_TOKEN": "gateway-token",
            },
        )

    def test_resolve_omits_unset_keys_and_has_no_file_fallback(self):
        with patch.dict(
            "os.environ",
            {"INOE_API_BASE_URL": "http://only-base"},
            clear=True,
        ):
            env = FIND_PROJECT._resolve_zgops_env()

        self.assertEqual(env, {"INOE_API_BASE_URL": "http://only-base"})
        self.assertFalse(hasattr(FIND_PROJECT, "_candidate_env_files"))
        self.assertFalse(hasattr(FIND_PROJECT, "_load_env_file"))

    def test_app_topology_uses_shared_env_resolver(self):
        with (
            patch.object(
                APP_TOPOLOGY,
                "_resolve_zgops_env",
                return_value={
                    "INOE_API_BASE_URL": "http://gateway.example.com:8080",
                    "INOE_API_TOKEN": "gateway-token",
                },
            ) as resolve_env,
            patch.object(APP_TOPOLOGY, "CmdbHttpClient") as client_cls,
            patch.object(APP_TOPOLOGY, "_fetch_relations", return_value=[]),
            patch.object(APP_TOPOLOGY, "_fetch_ci_detail", return_value={}),
            patch.object(APP_TOPOLOGY, "_resolve_inline_resources", return_value=[]),
            patch.object(sys, "argv", ["app_topology.py", "demo"]),
            patch.object(APP_TOPOLOGY, "print"),
        ):
            client = client_cls.return_value
            client.list_projects.return_value = [{"_id": 1, "project_name": "demo", "ci_type": "project"}]

            result = APP_TOPOLOGY.main()

        self.assertEqual(result, 0)
        resolve_env.assert_called_once_with()
        client_cls.assert_called_once_with(
            base_url="http://gateway.example.com:8080",
            token="gateway-token",
        )

    def test_configure_bearer_requires_token(self):
        session = requests.Session()
        ZGOPS_HTTP.configure_bearer(session, "gateway-token")
        self.assertEqual(session.headers["Authorization"], "Bearer gateway-token")
        with self.assertRaises(RuntimeError):
            ZGOPS_HTTP.configure_bearer(session, "")


if __name__ == "__main__":
    unittest.main()
