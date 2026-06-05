# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import logging
import os

import uvicorn

from qwenpaw.config.utils import write_last_api
from qwenpaw.constant import LOG_LEVEL_ENV
from qwenpaw.utils.logging import SuppressPathAccessLogFilter, setup_logger


def _env_int(name: str, default: int | None) -> int | None:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return int(raw_value)
    except ValueError:
        print(f"Invalid {name}={raw_value!r}; using {default!r}.")
        return default


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run QwenPaw FastAPI app with deployment-oriented uvicorn settings.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    parser.add_argument("--port", type=int, default=8088, help="Bind port.")
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Worker processes. Defaults to QWENPAW_APP_WORKERS or 1.",
    )
    parser.add_argument(
        "--backlog",
        type=int,
        default=None,
        help="Pending socket backlog. Defaults to QWENPAW_APP_BACKLOG or 2048.",
    )
    parser.add_argument(
        "--timeout-keep-alive",
        type=int,
        default=None,
        help="Keep-alive timeout in seconds. Defaults to QWENPAW_APP_TIMEOUT_KEEP_ALIVE or 5.",
    )
    parser.add_argument(
        "--limit-concurrency",
        type=int,
        default=None,
        help="Maximum concurrent requests. Defaults to QWENPAW_APP_LIMIT_CONCURRENCY if set.",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=("critical", "error", "warning", "info", "debug", "trace"),
        help="Log level.",
    )
    parser.add_argument(
        "--hide-access-path",
        "--hide-access-paths",
        action="append",
        default=["/console/push-messages"],
        help="Path substring to hide from uvicorn access logs. Repeatable.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    workers = max(1, args.workers or _env_int("QWENPAW_APP_WORKERS", 1) or 1)
    backlog = max(1, args.backlog or _env_int("QWENPAW_APP_BACKLOG", 2048) or 2048)
    timeout_keep_alive = max(
        1,
        args.timeout_keep_alive
        or _env_int("QWENPAW_APP_TIMEOUT_KEEP_ALIVE", 5)
        or 5,
    )
    limit_concurrency = args.limit_concurrency or _env_int(
        "QWENPAW_APP_LIMIT_CONCURRENCY",
        None,
    )
    if limit_concurrency is not None:
        limit_concurrency = max(1, limit_concurrency)

    os.environ[LOG_LEVEL_ENV] = args.log_level
    os.environ.pop("QWENPAW_RELOAD_MODE", None)
    setup_logger(args.log_level)

    paths = [path for path in args.hide_access_path if path]
    if paths:
        logging.getLogger("uvicorn.access").addFilter(
            SuppressPathAccessLogFilter(paths),
        )

    write_last_api("127.0.0.1" if args.host == "0.0.0.0" else args.host, args.port)

    uvicorn.run(
        "qwenpaw.app._app:app",
        host=args.host,
        port=args.port,
        workers=workers,
        backlog=backlog,
        timeout_keep_alive=timeout_keep_alive,
        limit_concurrency=limit_concurrency,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
