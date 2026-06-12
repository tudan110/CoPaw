# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

import pytest

from qwenpaw.extensions.ai_big_screen.capabilities import web_live
from qwenpaw.extensions.ai_big_screen.capabilities.web_live import (
    detect_kind,
    extract_currency_pair,
    extract_weather_location,
    fetch_web_live_data,
    sanitize_query,
)


class FakeResponse:
    def __init__(
        self,
        *,
        json_data: Any = None,
        text: str = "",
    ) -> None:
        self._json = json_data
        self.text = text

    def json(self) -> Any:
        return self._json


def _wttr_payload() -> dict[str, Any]:
    hourly = [{"time": str(h * 300), "tempC": str(20 + h)} for h in range(8)]
    return {
        "current_condition": [
            {
                "temp_C": "32",
                "FeelsLikeC": "35",
                "humidity": "40",
                "windspeedKmph": "12",
                "weatherDesc": [{"value": "Partly Cloudy "}],
                "lang_zh": [{"value": "局部多云"}],
            },
        ],
        "nearest_area": [
            {"areaName": [{"value": "Nanjing"}]},
        ],
        "weather": [
            {
                "date": "2026-06-11",
                "maxtempC": "35",
                "mintempC": "22",
                "hourly": hourly,
            },
            {
                "date": "2026-06-12",
                "maxtempC": "33",
                "mintempC": "21",
                "hourly": hourly,
            },
        ],
    }


_BING_HTML = (
    "<html><body><ol>"
    '<li class="b_algo"><h2><a href="https://www.weather.com.cn/x">'
    "南京<strong>天气</strong>预报</a></h2>"
    "<p>1 天前&ensp;&#0183;&ensp;南京天气预报，及时准确发布。</p></li>"
    '<li class="b_algo"><h2><a href="https://tianqi.so.com/y">'
    "南京一周天气</a></h2><p>七日预报详情。</p></li>"
    "</ol></body></html>"
)


class TestRouting:
    def test_detect_kind(self) -> None:
        assert detect_kind("南京天气") == "weather"
        assert detect_kind("美元兑人民币汇率") == "fx"
        assert detect_kind("最新 AI 行业新闻") == "web"

    def test_sanitize_query_strips_controls_and_caps(self) -> None:
        assert sanitize_query("a\x00b\x1fc") == "a b c"
        assert len(sanitize_query("长" * 500)) == 200

    def test_weather_location_extraction(self) -> None:
        assert extract_weather_location("查询南京天气") == "南京"
        assert extract_weather_location("明天上海的天气怎么样？") == "上海"

    def test_currency_pair_extraction(self) -> None:
        assert extract_currency_pair("美元兑人民币汇率") == ("USD", "CNY")
        assert extract_currency_pair("欧元 兑 日元") == ("EUR", "JPY")
        assert extract_currency_pair("汇率") == ("USD", "CNY")


class TestWeatherProvider:
    def test_parses_real_shape(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[str] = []

        def _fake_get(url: str, *, params: Any = None) -> FakeResponse:
            calls.append(url)
            assert params and params.get("format") == "j1"
            return FakeResponse(json_data=_wttr_payload())

        monkeypatch.setattr(web_live, "_http_get", _fake_get)
        data = fetch_web_live_data({"query": "查询南京天气"})
        assert "%E5%8D%97%E4%BA%AC" in calls[0]  # url-encoded 南京
        assert data["sourceStatus"] == "live"
        assert data["source"] == "wttr.in"
        assert data["value"] == 32
        assert data["unit"] == "°C"
        assert data["metrics"]["天气"] == "局部多云"
        assert data["rows"][0]["max"] == 35
        assert len(data["series"]) > 0
        assert data["series"][0]["y"] == 20
        # English aliases mirror the same real values so LLM
        # blueprint binds (temperature/condition/...) resolve
        assert data["metrics"]["temperature"] == 32
        assert data["metrics"]["condition"] == "局部多云"
        assert data["metrics"]["location"] == data["metrics"]["地点"]
        assert isinstance(data["metrics"]["humidity"], int)
        assert isinstance(data["metrics"]["feelsLike"], int)

    def test_provider_error_propagates(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _boom(url: str, *, params: Any = None) -> FakeResponse:
            raise ConnectionError("weather provider down")

        monkeypatch.setattr(web_live, "_http_get", _boom)
        with pytest.raises(ConnectionError):
            fetch_web_live_data({"query": "南京天气"})


class TestFxProvider:
    def test_parses_rates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = {
            "result": "success",
            "base_code": "USD",
            "time_last_update_utc": "Thu, 11 Jun 2026 00:02:31 +0000",
            "rates": {"CNY": 6.789317, "EUR": 0.92, "JPY": 155.1},
        }
        monkeypatch.setattr(
            web_live,
            "_http_get",
            lambda url, *, params=None: FakeResponse(json_data=payload),
        )
        data = fetch_web_live_data({"query": "美元兑人民币汇率"})
        assert data["sourceStatus"] == "live"
        assert data["value"] == 6.7893
        assert data["unit"] == "USD/CNY"
        assert any(row["pair"] == "USD/EUR" for row in data["rows"])

    def test_failure_result_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            web_live,
            "_http_get",
            lambda url, *, params=None: FakeResponse(
                json_data={"result": "error", "error-type": "quota"},
            ),
        )
        with pytest.raises(RuntimeError):
            fetch_web_live_data({"query": "汇率"})


class TestWebProvider:
    def test_parses_bing_results(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            web_live,
            "_http_get",
            lambda url, *, params=None: FakeResponse(text=_BING_HTML),
        )
        data = fetch_web_live_data({"query": "南京旅游攻略"})
        assert data["sourceStatus"] == "live"
        assert data["total"] == 2
        first = data["rows"][0]
        assert first["title"] == "南京天气预报"  # tags stripped
        assert "天气预报，及时准确发布" in first["snippet"]
        assert "&#" not in first["snippet"]  # entities unescaped
        assert first["source"] == "www.weather.com.cn"

    def test_zero_results_is_honest_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            web_live,
            "_http_get",
            lambda url, *, params=None: FakeResponse(text="<html></html>"),
        )
        data = fetch_web_live_data({"query": "不存在的内容xyz"})
        assert data["sourceStatus"] == "empty"
        assert data["rows"] == []


class TestEntryPoint:
    def test_empty_query_is_empty_not_crash(self) -> None:
        data = fetch_web_live_data({"query": "  "})
        assert data["sourceStatus"] == "empty"
        assert "query" in str(data.get("message"))

    def test_explicit_kind_overrides_detection(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            web_live,
            "_http_get",
            lambda url, *, params=None: FakeResponse(text=_BING_HTML),
        )
        # query says 天气 but kind=web forces generic search
        data = fetch_web_live_data({"query": "南京天气", "kind": "web"})
        assert data["source"] == "cn.bing.com"
