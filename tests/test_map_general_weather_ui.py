"""Contract checks for the manually queried map general-weather panel."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP_HTML = ROOT / "src" / "coral_rag" / "templates" / "map.html"
MAP_JS = ROOT / "src" / "coral_rag" / "static" / "map.js"
WEATHER_QUERY_JS = ROOT / "src" / "coral_rag" / "static" / "general-weather-query.js"


class MapGeneralWeatherUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = MAP_HTML.read_text(encoding="utf-8")
        cls.javascript = MAP_JS.read_text(encoding="utf-8")
        cls.query_javascript = WEATHER_QUERY_JS.read_text(encoding="utf-8")

    def test_selecting_a_site_only_resets_weather_and_never_auto_queries(self) -> None:
        select_body = self.javascript.split("function selectSite(site, origin) {", 1)[1].split(
            "function addMarker(site) {", 1
        )[0]
        self.assertIn("resetWeatherQuery(", select_body)
        self.assertNotIn("queryGeneralWeather(", select_body)
        self.assertIn('elements.weatherForm.addEventListener("submit"', self.javascript)
        self.assertIn("queryGeneralWeather();", self.javascript)
        self.assertIn('elements.weatherRange.addEventListener("change"', self.javascript)
        self.assertIn("clearWeatherDisplay()", self.javascript)

    def test_timezone_qualified_query_choices_and_request_race_gate(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is unavailable for the browser helper contract test")
        script = r"""
const assert = require("assert");
const query = require("./src/coral_rag/static/general-weather-query.js");
assert.deepStrictEqual([...query.ALLOWED_HOURS], [24, 48, 72]);
const now = new Date("2026-09-19T01:02:03.000Z");
const request = query.buildUrl("site / one", 24, now);
assert.strictEqual(request.startAt, "2026-09-19T09:02:03+08:00");
assert.strictEqual(request.endAt, "2026-09-20T09:02:03+08:00");
assert.strictEqual(request.timeZone, "Asia/Taipei");
assert.match(request.url, /start_at=2026-09-19T09%3A02%3A03%2B08%3A00/);
assert.match(request.url, /end_at=2026-09-20T09%3A02%3A03%2B08%3A00/);
assert.throws(() => query.buildUrl("site", 12, now), RangeError);
const gate = new query.RequestCoordinator();
const first = gate.start({siteId: "first", hours: 24});
const second = gate.start({siteId: "second", hours: 48});
assert.strictEqual(first.signal.aborted, true);
assert.strictEqual(gate.isCurrent(first, {siteId: "first", hours: 24}), false);
assert.strictEqual(gate.isCurrent(second, {siteId: "second", hours: 48}), true);
gate.cancel();
assert.strictEqual(second.signal.aborted, true);
console.log(JSON.stringify({timezone: request.timeZone, raceProtected: true}));
"""
        completed = subprocess.run(
            [node, "-e", script], cwd=ROOT, check=True, capture_output=True, text=True
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["timezone"], "Asia/Taipei")
        self.assertTrue(result["raceProtected"])

    def test_weather_fields_provenance_license_limitations_and_marine_gap_are_explicit(self) -> None:
        combined = self.html + self.javascript
        for label in (
            "行政區一般天氣預報",
            "DataTime",
            "天氣現象",
            "溫度",
            "3 小時降雨機率",
            "相對濕度",
            "風速",
            "風向",
            "原始資料未提供",
            "CWA 資料集 ID",
            "資料發布時間",
            "資料取得時間",
            "資料有效區間",
            "資料新鮮度狀態",
            "原始來源識別",
            "政府資料開放授權條款第 1 版（OGL 1.0）",
            "目前沒有可公開且足以代表此潛點的海況資料",
        ):
            with self.subTest(label=label):
                self.assertIn(label, combined)
        for limitation in (
            "不是潛點現場測量",
            "不代表波浪、海流、潮汐、近岸海況或水下狀況",
            "不可單獨用來判斷合法性、安全性或是否適合下水",
            "目前公開且可靠的海況資料不足",
        ):
            self.assertIn(limitation, self.html)
        self.assertNotIn("innerHTML", self.javascript)
        self.assertIn('url.protocol === "https:"', self.javascript)
        self.assertIn('link.rel = "noopener noreferrer"', self.javascript)

    def test_empty_and_error_statuses_clear_values_and_remain_accessible(self) -> None:
        for message in (
            "尚未查詢",
            "正在查詢行政區一般天氣預報",
            "沒有經明確官方行政區對應",
            "尚無已匯入且可用",
            "指定時間範圍沒有行政區一般天氣預報",
            "找不到目前選取的潛點（404）",
            "預報時間範圍無效（422）",
            "已過期或來源驗證失敗（503）",
            "行政區天氣 API 查詢失敗",
            "無法連線到行政區天氣 API",
            "未顯示任何舊預報值",
        ):
            with self.subTest(message=message):
                self.assertIn(message, self.html + self.javascript)
        self.assertIn('id="weather-results-region" aria-busy="false"', self.html)
        self.assertIn('role="status" aria-live="polite"', self.html)
        self.assertIn('cache: "no-store"', self.javascript)
        self.assertIn("weatherRequests.cancel()", self.javascript)
        self.assertIn("weatherRequests.isCurrent(token, currentWeatherContext())", self.javascript)

    def test_no_unapproved_forecast_source_or_marine_feature_is_added(self) -> None:
        combined = self.html + self.javascript + self.query_javascript
        self.assertIn("general-weather-forecast", combined)
        self.assertNotIn("marine-forecast", combined)
        self.assertNotIn("nearby-edna", self.query_javascript)
        self.assertNotIn("nearby-reef-check", self.query_javascript)
        self.assertNotIn("heatmap", combined.lower())
        self.assertNotIn("推薦", combined)


if __name__ == "__main__":
    unittest.main()
