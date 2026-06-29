#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import tempfile
import sys
from typing import Any
from urllib.parse import urljoin

import requests


def normalize_api_path(path: str) -> str:
    path = path.strip()
    if not path:
        raise ValueError("API 路径不能为空")
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return path


def build_url(base_url: str, path: str) -> str:
    path = normalize_api_path(path)
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"Accept-Language": "zh"})
    return session


class FallbackResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text

    def json(self) -> Any:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def _merged_headers(
    session: requests.Session,
    headers: dict[str, str] | None = None,
) -> dict[str, str]:
    merged = dict(session.headers)
    if headers:
        merged.update(headers)
    return {str(key): str(value) for key, value in merged.items() if value is not None}


def _should_fallback_to_curl(error: Exception) -> bool:
    if isinstance(error, requests.RequestException):
        return True
    if isinstance(error, OSError):
        return True
    return "No route to host" in str(error)


def _curl_request(
    *,
    url: str,
    method: str,
    headers: dict[str, str],
    json_payload: dict[str, Any] | None,
    timeout: int | float,
) -> FallbackResponse:
    with tempfile.NamedTemporaryFile(delete=False) as body_file:
        body_path = body_file.name

    args = [
        "curl",
        "-sS",
        "-X",
        method.upper(),
        "--connect-timeout",
        str(int(timeout)),
        "--max-time",
        str(int(timeout)),
        "-o",
        body_path,
        "-w",
        "%{http_code}",
    ]
    for key, value in headers.items():
        args.extend(["-H", f"{key}: {value}"])
    if json_payload is not None:
        args.extend(["--data-binary", json.dumps(json_payload, ensure_ascii=False)])
    args.append(url)

    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=max(int(timeout) + 5, 10),
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "curl 请求失败").strip())
        status_text = (completed.stdout or "").strip()
        status_code = int(status_text or "0")
        with open(body_path, "r", encoding="utf-8", errors="replace") as handle:
            body_text = handle.read()
        return FallbackResponse(status_code=status_code, text=body_text)
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            pass


def request_with_fallback(
    session: requests.Session,
    method: str,
    url: str,
    *,
    json_payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int | float = 30,
) -> requests.Response | FallbackResponse:
    try:
        return session.request(
            method=method.upper(),
            url=url,
            json=json_payload,
            headers=headers,
            timeout=timeout,
        )
    except Exception as error:  # noqa: BLE001
        if not _should_fallback_to_curl(error):
            raise
        return _curl_request(
            url=url,
            method=method,
            headers=_merged_headers(session, headers),
            json_payload=json_payload,
            timeout=timeout,
        )


def login(session: requests.Session, base_url: str, username: str, password: str) -> dict[str, Any]:
    url = build_url(base_url, "/api/v1/acl/login")
    response = request_with_fallback(
        session,
        "POST",
        url,
        json_payload={"username": username, "password": password},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("token")
    if not token:
        raise RuntimeError("登录响应缺少 token")
    session.headers["Access-Token"] = token
    return payload


def try_login(session: requests.Session, base_url: str, username: str, password: str) -> dict[str, Any] | None:
    if not str(username or "").strip() or not str(password or "").strip():
        return None
    try:
        return login(session, base_url, username, password)
    except Exception:
        return None


def parse_body(response: requests.Response) -> Any:
    try:
        return response.json()
    except json.JSONDecodeError:
        return response.text


def envelope(response: requests.Response) -> dict[str, Any]:
    return {"状态码": response.status_code, "响应体": parse_body(response)}


def _is_html_response(response: requests.Response | FallbackResponse) -> bool:
    """Detect if response is an HTML page (likely login redirect) instead of JSON."""
    content_type = ""
    if hasattr(response, "headers"):
        content_type = response.headers.get("Content-Type", "")
    if "text/html" in content_type:
        return True
    text = response.text if hasattr(response, "text") else ""
    if text.lstrip().startswith(("<!DOCTYPE", "<html", "<!doctype", "<HTML")):
        return True
    return False


def fetch_with_auth_fallback(
    session: requests.Session,
    *,
    base_url: str,
    path: str,
    username: str,
    password: str,
    timeout: int | float = 30,
) -> requests.Response | FallbackResponse:
    url = build_url(base_url, path)
    response = request_with_fallback(
        session,
        "GET",
        url,
        timeout=timeout,
    )
    # Retry on 401/403 or when response is HTML (session expired, redirected to login page)
    if response.status_code not in {401, 403} and not _is_html_response(response):
        return response

    auth_payload = try_login(session, base_url, username, password)
    if not auth_payload:
        return response

    return request_with_fallback(
        session,
        "GET",
        url,
        timeout=timeout,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="ZGOPS CMDB 后台 HTTP 客户端")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("login", help="后台登录并检查会话是否可用")

    fetch_parser = subparsers.add_parser("fetch", help="后台拉取指定 API")
    fetch_parser.add_argument("path", help="API 路径，例如 /api/v0.1/ci_types")

    args = parser.parse_args()

    base_url = os.environ["ZGOPS_BASE_URL"]
    username = os.environ.get("ZGOPS_USERNAME", "")
    password = os.environ.get("ZGOPS_PASSWORD", "")
    cmdb_url = os.environ.get("ZGOPS_CMDB_URL", base_url.rstrip("/") + "/cmdb/")

    session = create_session()

    try:
        auth_payload = try_login(session, base_url, username, password)

        if args.command == "login":
            if auth_payload:
                info_response = request_with_fallback(
                    session,
                    "GET",
                    build_url(base_url, "/api/v1/acl/users/info"),
                    timeout=20,
                )
                info_response.raise_for_status()
                info = parse_body(info_response)
            else:
                info = {}
            print(
                json.dumps(
                    {
                        "状态": "已登录" if auth_payload else "匿名访问",
                        "用户名": (auth_payload or {}).get("username", ""),
                        "CMDB": cmdb_url,
                        "用户信息": info.get("result", info),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        response = fetch_with_auth_fallback(
            session,
            base_url=base_url,
            path=args.path,
            username=username,
            password=password,
            timeout=30,
        )
        print(json.dumps(envelope(response), ensure_ascii=False, indent=2))
        return 0
    except requests.HTTPError as exc:
        response = exc.response
        if response is None:
            print(json.dumps({"状态码": 0, "响应体": str(exc)}, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps(envelope(response), ensure_ascii=False, indent=2))
        return 1
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps({"状态码": 0, "响应体": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2)
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
