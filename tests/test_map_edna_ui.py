"""Contract tests for the user-triggered nearby historical eDNA map panel."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP_HTML = ROOT / "src" / "coral_rag" / "templates" / "map.html"
MAP_JS = ROOT / "src" / "coral_rag" / "static" / "map.js"
EDNA_QUERY_JS = ROOT / "src" / "coral_rag" / "static" / "edna-query.js"


class MapNearbyEdnaUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = MAP_HTML.read_text(encoding="utf-8")
        cls.javascript = MAP_JS.read_text(encoding="utf-8")
        cls.query_javascript = EDNA_QUERY_JS.read_text(encoding="utf-8")

    def test_selecting_a_site_only_resets_controls_and_never_auto_queries(self) -> None:
        select_body = self.javascript.split("function selectSite(site, origin) {", 1)[1].split(
            "function addMarker(site) {", 1
        )[0]
        self.assertIn("resetEdnaQuery(", select_body)
        self.assertNotIn("queryNearbyEdna(", select_body)
        self.assertIn('elements.ednaForm.addEventListener("submit"', self.javascript)
        self.assertIn("queryNearbyEdna(0)", self.javascript)
        self.assertIn('elements.ednaRadius.addEventListener("change"', self.javascript)
        self.assertIn("clearEdnaDisplay()", self.javascript)

    def test_query_url_page_size_and_request_race_gate(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is unavailable for the browser helper contract test")
        script = r"""
const assert = require("assert");
const query = require("./src/coral_rag/static/edna-query.js");
assert.deepStrictEqual([...query.ALLOWED_RADII], [250, 500, 1000, 2500, 5000]);
assert.strictEqual(query.PAGE_SIZE, 10);
assert.strictEqual(
  query.buildUrl("site / one", 1000, 20),
  "/api/dive-sites/site%20%2F%20one/nearby-edna?radius_m=1000&limit=10&offset=20"
);
assert.throws(() => query.buildUrl("site", 200, 0), RangeError);
const gate = new query.RequestCoordinator();
const firstContext = {siteId: "first", radius: 500};
const secondContext = {siteId: "second", radius: 1000};
const first = gate.start(firstContext);
const second = gate.start(secondContext);
assert.strictEqual(first.signal.aborted, true);
assert.strictEqual(gate.isCurrent(first, firstContext), false);
assert.strictEqual(gate.isCurrent(second, secondContext), true);
gate.cancel();
assert.strictEqual(second.signal.aborted, true);
assert.strictEqual(gate.isCurrent(second, secondContext), false);
console.log(JSON.stringify({url: query.buildUrl("site", 500, 10), raceProtected: true}));
"""
        completed = subprocess.run(
            [node, "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(
            result["url"],
            "/api/dive-sites/site/nearby-edna?radius_m=500&limit=10&offset=10",
        )
        self.assertTrue(result["raceProtected"])

    def test_fields_source_license_missing_value_and_fixed_limitations_are_present(self) -> None:
        for label in (
            "附近歷史 eDNA 證據",
            "歷史 eDNA 檢出紀錄",
            "距代表點距離",
            "採樣日期",
            "原始站點名稱或 ID",
            "原始分類群（scientific_name）",
            "原始分類群（chinese_name）",
            "原始科別（family_name）",
            "原始科別（chinese_family）",
            "採樣深度",
            "原始來源紀錄 ID",
            "來源定位方式",
            "資料來源",
            "授權",
            "原始資料未提供",
        ):
            self.assertIn(label, self.html + self.javascript)

        for limitation in (
            "並非現場目擊或當日生物狀態",
            "距離接近不代表該生物存在於潛點或目前可見",
            "不是入口、活動範圍或採樣位置",
            "不能用來判斷合法性、安全性或是否適合下水",
            "政府資料開放授權條款第 1 版（OGL 1.0）",
        ):
            self.assertIn(limitation, self.html)
        self.assertNotIn("innerHTML", self.javascript)
        self.assertIn('link.rel = "noopener noreferrer"', self.javascript)
        self.assertIn('url.protocol === "https:"', self.javascript)

    def test_all_required_statuses_and_pagination_are_explicit(self) -> None:
        for message in (
            "尚未查詢",
            "正在查詢附近歷史 eDNA 證據",
            "指定半徑內沒有可回查",
            "找不到目前選取的潛點（404）",
            "查詢半徑或分頁參數無效（422）",
            "資料庫版本尚未就緒（503）",
            "歷史 eDNA API 查詢失敗",
            "無法連線到歷史 eDNA API",
        ):
            self.assertIn(message, self.html + self.javascript)
        self.assertIn('aria-busy="false"', self.html)
        self.assertIn("currentEdnaNextOffset", self.javascript)
        self.assertIn("currentEdnaOffset - ednaTools.PAGE_SIZE", self.javascript)
        self.assertIn("pagination.next_offset", self.javascript)
        self.assertIn("符合條件總筆數", self.javascript)
        self.assertIn("顯示第 ${rangeStart}–${rangeEnd} 筆", self.javascript)

    def test_edna_remains_separate_from_forbidden_layers_and_reef_check_transport(self) -> None:
        combined = self.html + self.javascript + self.query_javascript
        self.assertNotIn("nearby-reef-check", self.query_javascript)
        self.assertNotIn("heatmap", combined.lower())
        self.assertNotIn("circleMarker", combined)
        self.assertNotIn("這裡有的魚", combined)
        self.assertNotIn("常見魚種", combined)
        self.assertNotIn("生物豐富度", combined)


if __name__ == "__main__":
    unittest.main()
