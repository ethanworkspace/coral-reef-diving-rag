"""Contract checks for the manual, license-gated Reef Check map panel."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP_HTML = ROOT / "src" / "coral_rag" / "templates" / "map.html"
MAP_JS = ROOT / "src" / "coral_rag" / "static" / "map.js"
REEFCHECK_QUERY_JS = ROOT / "src" / "coral_rag" / "static" / "reefcheck-query.js"
START_SCRIPT = ROOT / "scripts" / "run_local_research.ps1"


class MapReefCheckUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = MAP_HTML.read_text(encoding="utf-8")
        cls.javascript = MAP_JS.read_text(encoding="utf-8")
        cls.query_javascript = REEFCHECK_QUERY_JS.read_text(encoding="utf-8")
        cls.start_script = START_SCRIPT.read_text(encoding="utf-8")

    def test_selecting_site_resets_without_automatic_reef_check_request(self) -> None:
        select_body = self.javascript.split("function selectSite(site, origin) {", 1)[1].split(
            "function addMarker(site) {", 1
        )[0]
        self.assertIn("resetReefCheckQuery(", select_body)
        self.assertNotIn("queryNearbyReefCheck(", select_body)
        self.assertIn('elements.reefCheckForm.addEventListener("submit"', self.javascript)
        self.assertIn("queryNearbyReefCheck(0)", self.javascript)
        self.assertIn('elements.reefCheckRadius.addEventListener("change"', self.javascript)
        self.assertIn("clearReefCheckDisplay()", self.javascript)

    def test_query_url_paging_and_request_race_gate(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is unavailable for the browser helper contract test")
        script = r'''
const assert = require("assert");
const query = require("./src/coral_rag/static/reefcheck-query.js");
assert.deepStrictEqual([...query.ALLOWED_RADII], [250, 500, 1000, 2500, 5000]);
assert.strictEqual(query.PAGE_SIZE, 10);
assert.strictEqual(query.buildUrl("site / one", 1000, 20), "/api/dive-sites/site%20%2F%20one/nearby-reef-check?radius_m=1000&limit=10&offset=20");
assert.throws(() => query.buildUrl("site", 200, 0), RangeError);
const gate = new query.RequestCoordinator();
const first = gate.start({siteId: "first", radius: 500});
const second = gate.start({siteId: "second", radius: 1000});
assert.strictEqual(first.signal.aborted, true);
assert.strictEqual(gate.isCurrent(first, {siteId: "first", radius: 500}), false);
assert.strictEqual(gate.isCurrent(second, {siteId: "second", radius: 1000}), true);
gate.cancel();
assert.strictEqual(second.signal.aborted, true);
console.log(JSON.stringify({raceProtected: true}));
'''
        result = subprocess.run([node, "-e", script], cwd=ROOT, check=True, capture_output=True, text=True)
        self.assertTrue(json.loads(result.stdout)["raceProtected"])

    def test_license_restricted_status_fields_and_non_mixing_are_explicit(self) -> None:
        combined = self.html + self.javascript
        for text in (
            "附近歷史 Reef Check 目視證據", "Reef Check 僅在已啟用的本機非商業研究模式中可用",
            "CC BY-NC 4.0", "距代表點距離", "原始事件 ID", "原始觀測 ID", "調查日期",
            "座標不確定度", "資料解讀、授權與使用限制", "不得據此公開部署或商業使用",
        ):
            self.assertIn(text, combined)
        self.assertIn("response.status === 403", self.javascript)
        self.assertIn("clearReefCheckDisplay()", self.javascript)
        self.assertNotIn("recorded_by", self.javascript)
        self.assertIn("ednaResults", self.javascript)
        self.assertIn("reefCheckResults", self.javascript)
        self.assertNotIn("heatmap", combined.lower())
        self.assertNotIn("circleMarker", combined)
        self.assertNotIn("biodiversity", combined.lower())
        self.assertNotIn("iAI", combined)

    def test_all_result_states_are_accessible_and_script_opt_in_is_nonpersistent(self) -> None:
        for text in (
            "尚未查詢", "正在查詢附近歷史 Reef Check 目視證據", "沒有可回查的歷史 Reef Check",
            "（404）", "（422）", "（503）", "API 查詢失敗", "無法連線至 Reef Check API",
        ):
            self.assertIn(text, self.html + self.javascript)
        self.assertIn('id="reefcheck-results-region" aria-busy="false"', self.html)
        self.assertIn('role="status" aria-live="polite"', self.html)
        self.assertIn("reefCheckRequests.cancel()", self.javascript)
        self.assertIn("reefCheckRequests.isCurrent(token, currentReefCheckContext())", self.javascript)
        self.assertIn("[switch]$EnableReefCheckLocalResearch", self.start_script)
        self.assertIn("if ($EnableReefCheckLocalResearch)", self.start_script)
        self.assertIn("$env:REEFCHECK_LOCAL_NONCOMMERCIAL_RESEARCH_MODE = 'enabled'", self.start_script)
        self.assertNotIn("setx", self.start_script.lower())
        self.assertNotIn("[Environment]::SetEnvironmentVariable", self.start_script)
