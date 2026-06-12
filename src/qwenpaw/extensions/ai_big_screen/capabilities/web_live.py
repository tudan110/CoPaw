# -*- coding: utf-8 -*-
"""``web-live-data`` capability: real public-internet data, keyless.

The universal fallback for asks outside the specialized ops
capabilities (spec: "数据不设限"). A provider router dispatches by
query intent:

- ``weather``  wttr.in ``?format=j1`` (accepts Chinese place names)
- ``fx``       open.er-api.com latest rates
- ``web``      cn.bing.com HTML search, defensively parsed

Hard rules: every row comes from a live HTTP response with the source
attributed — never from model knowledge; provider failure propagates so
the registry adjudicates an honest ``failed``; all extracted text is
tag-stripped, entity-unescaped and length-capped before it can reach a
screen. Providers are a fixed allowlist — the LLM supplies only the
query text, never a URL.
"""
from __future__ import annotations

import html as html_lib
import re
from typing import Any, Mapping
from urllib.parse import quote

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_HTTP_TIMEOUT_SECONDS = 8.0
_MAX_QUERY_LENGTH = 200

_WEATHER_RE = re.compile(r"天气|气温|weather", re.IGNORECASE)
_FX_RE = re.compile(
    r"汇率|exchange\s*rate|兑换?|USD|CNY|EUR|JPY|GBP|HKD|美元|人民币|欧元|日元|英镑|港币",
    re.IGNORECASE,
)

_CURRENCY_ALIASES = [
    ("USD", ("usd", "美元", "美金")),
    ("CNY", ("cny", "rmb", "人民币", "元")),
    ("EUR", ("eur", "欧元")),
    ("JPY", ("jpy", "日元")),
    ("GBP", ("gbp", "英镑")),
    ("HKD", ("hkd", "港币", "港元")),
]

_WMO_FALLBACK_DESC = "未知天气"

_BING_ITEM_RE = re.compile(r'<li class="b_algo".*?</li>', re.DOTALL)
_BING_TITLE_RE = re.compile(
    r'<h2[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_BING_SNIPPET_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_HOST_RE = re.compile(r"https?://([^/]+)")


def _http_get(url: str, *, params: Mapping[str, Any] | None = None) -> Any:
    """Single egress point (kept tiny so tests can monkeypatch it)."""
    import httpx

    response = httpx.get(
        url,
        params=dict(params or {}),
        headers={"User-Agent": _USER_AGENT},
        timeout=_HTTP_TIMEOUT_SECONDS,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response


def _clean_text(raw: Any, *, max_length: int) -> str:
    text = _TAG_RE.sub("", str(raw or ""))
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_length]


def sanitize_query(raw: Any) -> str:
    query = re.sub(r"[\x00-\x1f\x7f]", " ", str(raw or ""))
    return re.sub(r"\s+", " ", query).strip()[:_MAX_QUERY_LENGTH]


def detect_kind(query: str) -> str:
    if _WEATHER_RE.search(query):
        return "weather"
    if _FX_RE.search(query):
        return "fx"
    return "web"


# ---------------------------------------------------------------------------
# weather — wttr.in
# ---------------------------------------------------------------------------

_LOCATION_NOISE_RE = re.compile(
    r"查询|查看|看一下|看下|展示|显示|搜索|今天|明天|后天|未来|最近|当前|"
    r"现在|实时|一周|几天|天气预报|天气|气温|温度|情况|怎么样|如何|预报|"
    r"weather|forecast|的|了|呢|？|\?|，|,|。",
    re.IGNORECASE,
)


def extract_weather_location(query: str) -> str:
    location = _LOCATION_NOISE_RE.sub("", query)
    return re.sub(r"\s+", "", location).strip()[:40]


def _weather_desc(condition: Mapping[str, Any]) -> str:
    for key in ("lang_zh", "weatherDesc"):
        values = condition.get(key)
        if isinstance(values, list) and values:
            text = _clean_text(
                (values[0] or {}).get("value"),
                max_length=40,
            )
            if text:
                return text
    return _WMO_FALLBACK_DESC


def _fetch_weather(query: str) -> dict[str, Any]:
    location = extract_weather_location(query)
    path = quote(location) if location else ""
    response = _http_get(
        f"https://wttr.in/{path}",
        params={"format": "j1", "lang": "zh"},
    )
    payload = response.json()
    current = (payload.get("current_condition") or [{}])[0]
    area = (payload.get("nearest_area") or [{}])[0]
    area_name = _clean_text(
        ((area.get("areaName") or [{}])[0] or {}).get("value"),
        max_length=40,
    ) or (location or "本地")
    desc = _weather_desc(current)
    temp = int(float(current.get("temp_C") or 0))
    feels = int(float(current.get("FeelsLikeC") or 0))
    humidity = int(float(current.get("humidity") or 0))
    wind_kmh = int(float(current.get("windspeedKmph") or 0))

    day_rows: list[dict[str, Any]] = []
    hourly_series: list[dict[str, Any]] = []
    for day in list(payload.get("weather") or [])[:3]:
        date = _clean_text(day.get("date"), max_length=20)
        day_rows.append(
            {
                "date": date,
                "desc": _weather_desc(
                    ((day.get("hourly") or [{}]) or [{}])[
                        len(day.get("hourly") or []) // 2
                    ]
                    if day.get("hourly")
                    else {},
                ),
                "max": int(float(day.get("maxtempC") or 0)),
                "min": int(float(day.get("mintempC") or 0)),
            },
        )
        for hour in day.get("hourly") or []:
            minutes = int(float(hour.get("time") or 0))
            hourly_series.append(
                {
                    "x": f"{date[5:]} {minutes // 100:02d}时",
                    "y": int(float(hour.get("tempC") or 0)),
                },
            )

    return {
        "source": "wttr.in",
        "sourceStatus": "live",
        "value": temp,
        "unit": "°C",
        "trend": f"{area_name} 当前 {desc}，体感 {feels}°C",
        "metrics": {
            "气温": f"{temp}°C",
            "天气": desc,
            "体感": f"{feels}°C",
            "湿度": f"{humidity}%",
            "风速": f"{wind_kmh} km/h",
            "地点": area_name,
            # English aliases: LLM blueprints habitually bind
            # temperature/condition/...; resolve them to the same
            # real values (bare numbers so atoms can add units)
            "temperature": temp,
            "condition": desc,
            "feelsLike": feels,
            "humidity": humidity,
            "wind": f"{wind_kmh} km/h",
            "location": area_name,
        },
        "columns": [
            {"key": "date", "label": "日期"},
            {"key": "desc", "label": "天气"},
            {"key": "max", "label": "最高°C"},
            {"key": "min", "label": "最低°C"},
        ],
        "rows": day_rows,
        "series": hourly_series[:24],
        "total": len(day_rows),
    }


# ---------------------------------------------------------------------------
# fx — open.er-api.com
# ---------------------------------------------------------------------------


def extract_currency_pair(query: str) -> tuple[str, str]:
    lowered = query.lower()
    # Collect every alias occurrence, then sweep keeping non-overlapping
    # matches with longer aliases winning — so the bare "元" in CNY's
    # aliases cannot fire inside 欧元/日元/美元.
    occurrences: list[tuple[int, int, str]] = []
    for code, aliases in _CURRENCY_ALIASES:
        for alias in aliases:
            start = lowered.find(alias)
            while start >= 0:
                occurrences.append((start, len(alias), code))
                start = lowered.find(alias, start + 1)
    occurrences.sort(key=lambda item: (item[0], -item[1]))
    deduped: list[str] = []
    claimed_until = -1
    for position, length, code in occurrences:
        if position < claimed_until:
            continue
        claimed_until = position + length
        if code not in deduped:
            deduped.append(code)
    base = deduped[0] if deduped else "USD"
    quote_code = next(
        (code for code in deduped[1:] if code != base),
        "CNY" if base != "CNY" else "USD",
    )
    return base, quote_code


def _fetch_fx(query: str) -> dict[str, Any]:
    base, quote_code = extract_currency_pair(query)
    response = _http_get(f"https://open.er-api.com/v6/latest/{quote(base)}")
    payload = response.json()
    if str(payload.get("result")) != "success":
        raise RuntimeError(
            f"汇率服务返回异常：{payload.get('error-type') or 'unknown'}",
        )
    rates = payload.get("rates") or {}
    rate = rates.get(quote_code)
    if not isinstance(rate, (int, float)):
        raise RuntimeError(f"汇率服务未提供 {base}/{quote_code} 报价")
    majors = ["CNY", "USD", "EUR", "JPY", "GBP", "HKD"]
    rows = [
        {"pair": f"{base}/{code}", "rate": round(float(rates[code]), 4)}
        for code in majors
        if code != base and isinstance(rates.get(code), (int, float))
    ]
    return {
        "source": "open.er-api.com",
        "sourceStatus": "live",
        "value": round(float(rate), 4),
        "unit": f"{base}/{quote_code}",
        "trend": "汇率更新于 "
        + _clean_text(payload.get("time_last_update_utc"), max_length=40),
        "metrics": {
            f"{base}/{quote_code}": round(float(rate), 4),
            # English alias for LLM blueprint binds
            "rate": round(float(rate), 4),
        },
        "columns": [
            {"key": "pair", "label": "货币对"},
            {"key": "rate", "label": "汇率"},
        ],
        "rows": rows,
        "total": len(rows),
    }


# ---------------------------------------------------------------------------
# web — cn.bing.com HTML search (best effort, defensively parsed)
# ---------------------------------------------------------------------------


def _fetch_web_search(query: str) -> dict[str, Any]:
    response = _http_get(
        "https://cn.bing.com/search",
        params={"q": query},
    )
    items = _BING_ITEM_RE.findall(response.text or "")
    rows: list[dict[str, Any]] = []
    for item in items[:8]:
        title_match = _BING_TITLE_RE.search(item)
        if not title_match:
            continue
        url = str(title_match.group(1) or "")
        title = _clean_text(title_match.group(2), max_length=80)
        if not title:
            continue
        snippet_match = _BING_SNIPPET_RE.search(item)
        snippet = (
            _clean_text(snippet_match.group(1), max_length=160)
            if snippet_match
            else ""
        )
        host_match = _HOST_RE.match(url)
        rows.append(
            {
                "title": title,
                "snippet": snippet,
                "source": host_match.group(1)[:60] if host_match else "",
            },
        )
    if not rows:
        return {
            "source": "cn.bing.com",
            "sourceStatus": "empty",
            "message": "公开检索未命中结果",
            "rows": [],
            "total": 0,
        }
    return {
        "source": "cn.bing.com",
        "sourceStatus": "live",
        "trend": f"必应实时检索 Top {len(rows)}",
        "columns": [
            {"key": "title", "label": "标题"},
            {"key": "snippet", "label": "摘要"},
            {"key": "source", "label": "来源"},
        ],
        "rows": rows,
        "total": len(rows),
    }


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

_PROVIDERS = {
    "weather": _fetch_weather,
    "fx": _fetch_fx,
    "web": _fetch_web_search,
}


def fetch_web_live_data(query_params: Mapping[str, Any]) -> dict[str, Any]:
    query = sanitize_query(query_params.get("query"))
    if not query:
        return {
            "source": "web-live-providers",
            "sourceStatus": "empty",
            "message": "未提供检索内容（queryParams.query 为空）",
            "rows": [],
            "total": 0,
        }
    requested_kind = str(query_params.get("kind") or "auto").strip().lower()
    kind = (
        requested_kind
        if requested_kind in _PROVIDERS
        else detect_kind(
            query,
        )
    )
    data = _PROVIDERS[kind](query)
    data.setdefault("query", query)
    data.setdefault("provider", kind)
    return data
