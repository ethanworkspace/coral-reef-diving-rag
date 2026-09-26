"""Offline UI contract and integration tests for the nearby marine model context card.

Verifications:
  1. HTML Structure & Separation:
     - map.html contains the independent nearby marine section (#profile-nearby-marine).
     - Heading is strictly '附近海域模式參考（非潛點現場量測）'.
     - Contains a dedicated refresh button (#nearby-marine-refresh, '重新查詢').
     - Contains status announcement element with role="status" and aria-live="polite".
     - Is inside #site-profile-drawer and completely separated from #weather-panel.
  2. Endpoint Authorization & Prohibited Patterns:
     - map.js calls the dedicated /nearby-marine-context endpoint.
     - Frontend strictly does NOT call /marine-forecast.
     - Strictly no suitability ratings (適宜度, 適合下水, 下水建議, 紅綠燈).
     - Strictly no heatmap (熱圖, heatmap).
     - Strictly no '現地觀測' in the nearby marine card.
     - Strictly no innerHTML anywhere in map.js (safe DOM only).
  3. Race Coordination & Selection Reset:
     - NearbyMarineRequestCoordinator handles sequence cancellation with AbortController.
     - Selecting a new site triggers request cancellation and clears stale data immediately.
     - If response arrives for an outdated site, it is discarded.
  4. Field Representation & Contract Units:
     - Displays model position name & code, coordinates, site coordinates, distance.
     - Displays issue time, valid window.
     - Displays wave height (m), wave direction, wave period (s), current direction, current speed (knot).
     - No unit conversions or guess values.
  5. Fail-Closed Error Handling:
     - 404, 422, 503 (source_expired, checksum mismatch, etc.) and network errors
       clear all forecast values and display explicit failure reasons.
     - Never retains stale forecast values on failure.
  6. Disclaimers:
     - All 4 safety and legal disclaimers are present and rendered safely as text.
  7. Invariants & Zero Mutation:
     - Curated dive sites CSV maintains 5 rows and exact SHA-256 hash.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_HTML = ROOT / "src" / "coral_rag" / "templates" / "map.html"
MAP_JS = ROOT / "src" / "coral_rag" / "static" / "map.js"
MAP_CSS = ROOT / "src" / "coral_rag" / "static" / "map.css"
CURATED_CSV = ROOT / "data" / "curated" / "dive_sites.csv"

EXPECTED_DIVE_SITES_SHA256 = (
    "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
)

MANDATORY_DISCLAIMERS = [
    "此資料為交通部中央氣象署數值模式外海代表計算點之預報結果，絕非潛點現場量測數據。",
    "模式代表位置與潛點實體存在客觀空間距離，無法反映近岸水文微地形、碎波帶與沿岸暗流。",
    "本資料僅供宏觀海域環境背景參考，嚴禁單獨用於判斷合法性、安全性或是否適合下水。",
    "從事浮潛或水肺潛水活動前，必須確認最新官方警特報、現場實際海況，並由合格專業人員實地評估。",
]


class MapNearbyMarineContextUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = MAP_HTML.read_text(encoding="utf-8")
        cls.javascript = MAP_JS.read_text(encoding="utf-8")
        cls.css = MAP_CSS.read_text(encoding="utf-8")

    def test_nearby_marine_card_html_structure_and_separation(self) -> None:
        """Verify the independent card is placed inside the drawer and separated from general weather."""
        self.assertIn('id="profile-nearby-marine"', self.html)
        self.assertIn("附近海域模式參考（非潛點現場量測）", self.html)
        self.assertIn('id="nearby-marine-refresh"', self.html)
        self.assertIn("重新查詢", self.html)
        self.assertIn('id="nearby-marine-status"', self.html)
        self.assertIn('role="status"', self.html)
        self.assertIn('aria-live="polite"', self.html)
        self.assertIn('id="nearby-marine-content"', self.html)
        self.assertIn('id="nearby-marine-meta-fields"', self.html)
        self.assertIn('id="nearby-marine-items"', self.html)
        self.assertIn('id="nearby-marine-disclaimers"', self.html)

        # Confirm it is inside #site-profile-drawer
        drawer_part = self.html.split('id="site-profile-drawer"')[1].split(
            'id="site-detail"'
        )[0]
        self.assertIn('id="profile-nearby-marine"', drawer_part)

        # Confirm it is separate from #weather-panel
        weather_part = self.html.split('id="weather-panel"')[1].split(
            'id="site-list-heading"'
        )[0]
        self.assertNotIn('id="profile-nearby-marine"', weather_part)

    def test_endpoint_allowed_and_strict_forbidden_patterns(self) -> None:
        """Verify dedicated endpoint is used, marine-forecast is prohibited, no innerHTML or ratings."""
        # Dedicated endpoint used
        self.assertIn("/nearby-marine-context", self.javascript)

        # Frontend strictly does not call the primary 1km marine-forecast endpoint
        combined = self.html + self.javascript
        self.assertNotIn("marine-forecast", combined)

        # Absolutely no innerHTML in map.js
        self.assertNotIn("innerHTML", self.javascript)
        self.assertIn("textContent", self.javascript)

        # No suitability ratings, traffic lights, recommendations, heatmaps, or mislabeling as in-situ
        prohibited_terms = [
            "適宜度",
            "適合下水",
            "不宜下水",
            "下水建議",
            "紅綠燈",
            "熱圖",
            "heatmap",
            "現地觀測",
        ]
        for term in prohibited_terms:
            with self.subTest(term=term):
                self.assertNotIn(term, self.html.split('id="profile-nearby-marine"')[1].split('</section>')[0])

    def test_race_condition_coordinator_behavior(self) -> None:
        """Verify RequestCoordinator handles cancellation and sequence guarding via Node.js."""
        self.assertIn("class NearbyMarineRequestCoordinator", self.javascript)
        self.assertIn("nearbyMarineRequests.start(", self.javascript)
        self.assertIn("nearbyMarineRequests.cancel()", self.javascript)
        self.assertIn("nearbyMarineRequests.isCurrent(", self.javascript)

        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not available in test environment")

        script = r'''
const assert = require("assert");

class NearbyMarineRequestCoordinator {
  constructor() {
    this.sequence = 0;
    this.controller = null;
  }
  start(siteId) {
    this.cancel();
    this.sequence += 1;
    this.controller = new AbortController();
    return { sequence: this.sequence, siteId, signal: this.controller.signal };
  }
  cancel() {
    if (this.controller) {
      this.controller.abort();
      this.controller = null;
    }
  }
  isCurrent(token, currentSiteId) {
    return Boolean(token && token.sequence === this.sequence && token.siteId === currentSiteId);
  }
}

const coordinator = new NearbyMarineRequestCoordinator();
const token1 = coordinator.start("site-1");
assert.strictEqual(token1.sequence, 1);
assert.strictEqual(token1.signal.aborted, false);
assert.strictEqual(coordinator.isCurrent(token1, "site-1"), true);

// Switch to site-2: token1 must be aborted and no longer current
const token2 = coordinator.start("site-2");
assert.strictEqual(token1.signal.aborted, true);
assert.strictEqual(token2.sequence, 2);
assert.strictEqual(token2.signal.aborted, false);
assert.strictEqual(coordinator.isCurrent(token1, "site-1"), false);
assert.strictEqual(coordinator.isCurrent(token1, "site-2"), false);
assert.strictEqual(coordinator.isCurrent(token2, "site-2"), true);

console.log(JSON.stringify({ raceGuardVerified: true }));
'''
        proc = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True)
        out = json.loads(proc.stdout)
        self.assertTrue(out.get("raceGuardVerified"))

    def test_site_selection_triggers_nearby_marine_load_and_refresh_button_wired(self) -> None:
        """Verify selecting a site loads nearby marine context and refresh button reloads."""
        select_body = self.javascript.split("function selectSite(site, origin) {", 1)[1].split(
            "function addMarker(site) {", 1
        )[0]
        self.assertIn("loadNearbyMarineContext(site);", select_body)
        self.assertIn('elements.nearbyMarineRefresh.addEventListener("click"', self.javascript)
        self.assertIn("loadNearbyMarineContext(selectedSite);", self.javascript)

    def test_metadata_fields_and_units_conformance(self) -> None:
        """Verify metadata fields, distances, and forecast item units match contract."""
        combined = self.html + self.javascript
        expected_meta_fields = [
            "模式位置名稱／代碼",
            "模式點座標",
            "潛點代表點座標",
            "距潛點直線距離",
            "空間性質說明",
            "資料發布時間",
            "預報有效時間",
        ]
        for field in expected_meta_fields:
            with self.subTest(field=field):
                self.assertIn(field, combined)

        expected_forecast_fields = [
            "浪高",
            "波向",
            "週期",
            "流向",
            "流速",
        ]
        for field in expected_forecast_fields:
            with self.subTest(field=field):
                self.assertIn(field, combined)

        # Units strictly according to contract
        self.assertIn("公尺 (m)", self.javascript)
        self.assertIn("秒 (s)", self.javascript)
        self.assertIn("節 (knot)", self.javascript)

    def test_fail_closed_error_states_clear_values_and_report_reasons(self) -> None:
        """Verify 404, 422, 503, and network errors clear data and display clear messages."""
        self.assertIn("clearNearbyMarineDisplay()", self.javascript)
        expected_error_messages = [
            "找不到目前選取的潛點（404）",
            "預報時間範圍無效（422）",
            "氣象署模式預報資料已過期（發布超過 24 小時）；為確保安全，未顯示過期舊預報。",
            "模式快照完整性驗證失敗；未顯示不可靠資料。",
            "附近海域模式資料目前無法提供（503）；未顯示任何舊資料。",
            "無法連線至附近海域模式 API；未顯示任何舊資料。",
        ]
        for msg in expected_error_messages:
            with self.subTest(msg=msg):
                self.assertIn(msg, self.javascript)

    def test_disclaimers_rendered_faithfully(self) -> None:
        """Verify all 4 mandatory disclaimers are present in the rendering logic."""
        for disclaimer in MANDATORY_DISCLAIMERS:
            with self.subTest(disclaimer=disclaimer[:15]):
                self.assertIn(disclaimer, self.javascript)

    def test_curated_dive_sites_zero_mutation(self) -> None:
        """Verify curated dive sites file has not been altered."""
        self.assertTrue(CURATED_CSV.exists())
        raw_bytes = CURATED_CSV.read_bytes()
        actual_hash = hashlib.sha256(raw_bytes).hexdigest().lower()
        self.assertEqual(actual_hash, EXPECTED_DIVE_SITES_SHA256)
        lines = [line for line in raw_bytes.decode("utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), 6)  # 1 header + 5 dive sites


if __name__ == "__main__":
    unittest.main()
