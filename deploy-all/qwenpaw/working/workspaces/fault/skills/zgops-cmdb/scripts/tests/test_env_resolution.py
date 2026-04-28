import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCRIPT_DIR = Path(__file__).resolve().parents[1]
FIND_PROJECT = _load_module("veops_find_project_test", SCRIPT_DIR / "find_project.py")
APP_TOPOLOGY = _load_module("veops_app_topology_test", SCRIPT_DIR / "app_topology.py")
VEOPS_HTTP = _load_module("veops_http_test", SCRIPT_DIR / "veops_http.py")


class VeopsCmdbEnvResolutionTests(unittest.TestCase):
    def test_find_project_uses_skill_local_env_file(self):
        env_path = FIND_PROJECT._default_env_file()

        self.assertEqual(env_path, SCRIPT_DIR.parent / ".env")

    def test_app_topology_uses_skill_local_env_file(self):
        env_path = APP_TOPOLOGY._default_env_file()

        self.assertEqual(env_path, SCRIPT_DIR.parent / ".env")

    def test_try_login_returns_none_when_credentials_missing(self):
        session = object()

        self.assertIsNone(VEOPS_HTTP.try_login(session, "http://cmdb.example.com", "", ""))

    def test_try_login_returns_none_when_login_fails(self):
        session = object()
        with patch.object(VEOPS_HTTP, "login", side_effect=RuntimeError("boom")):
            result = VEOPS_HTTP.try_login(session, "http://cmdb.example.com", "user", "pass")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
