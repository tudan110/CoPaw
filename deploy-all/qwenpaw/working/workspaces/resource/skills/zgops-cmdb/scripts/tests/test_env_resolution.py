import importlib.util
import sys
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
sys.path.insert(0, str(SCRIPT_DIR))
FIND_PROJECT = _load_module("zgops_find_project_test", SCRIPT_DIR / "find_project.py")
APP_TOPOLOGY = _load_module("zgops_app_topology_test", SCRIPT_DIR / "app_topology.py")
ZGOPS_HTTP = _load_module("zgops_http_test", SCRIPT_DIR / "zgops_http.py")


class ZgopsCmdbEnvResolutionTests(unittest.TestCase):
    def test_find_project_prefers_shared_secret_before_skill_local_env(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(Path, "home", return_value=Path("/home/test")),
        ):
            env_paths = FIND_PROJECT._candidate_env_files()

        self.assertEqual(
            env_paths,
            [
                SCRIPT_DIR.parents[4] / "secrets" / "zgops-cmdb.env",
                Path("/home/test/.qwenpaw/secrets/zgops-cmdb.env"),
                SCRIPT_DIR.parent / ".env",
            ],
        )

    def test_find_project_honors_explicit_and_working_secret_order(self):
        with (
            patch.dict(
                "os.environ",
                {
                    "ZGOPS_ENV_FILE": "/tmp/custom.env",
                    "QWENPAW_WORKING_DIR": "/work/qwenpaw",
                },
                clear=True,
            ),
            patch.object(Path, "home", return_value=Path("/home/test")),
        ):
            env_paths = FIND_PROJECT._candidate_env_files()

        self.assertEqual(
            env_paths,
            [
                Path("/tmp/custom.env"),
                Path("/work/qwenpaw/secrets/zgops-cmdb.env"),
                SCRIPT_DIR.parents[4] / "secrets" / "zgops-cmdb.env",
                Path("/home/test/.qwenpaw/secrets/zgops-cmdb.env"),
                SCRIPT_DIR.parent / ".env",
            ],
        )

    def test_app_topology_uses_shared_env_resolver(self):
        with (
            patch.object(
                APP_TOPOLOGY,
                "_resolve_zgops_env",
                return_value={"ZGOPS_BASE_URL": "http://cmdb.example.com"},
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
            base_url="http://cmdb.example.com",
            username="",
            password="",
        )

    def test_try_login_returns_none_when_credentials_missing(self):
        session = object()

        self.assertIsNone(ZGOPS_HTTP.try_login(session, "http://cmdb.example.com", "", ""))

    def test_try_login_returns_none_when_login_fails(self):
        session = object()
        with patch.object(ZGOPS_HTTP, "login", side_effect=RuntimeError("boom")):
            result = ZGOPS_HTTP.try_login(session, "http://cmdb.example.com", "user", "pass")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
