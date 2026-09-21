"""Offline contract tests for the source-governed dive-site profile drawer."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP_HTML = ROOT / "src" / "coral_rag" / "templates" / "map.html"
MAP_JS = ROOT / "src" / "coral_rag" / "static" / "map.js"
PROFILE_QUERY_JS = ROOT / "src" / "coral_rag" / "static" / "dive-site-profile-query.js"
MAP_CSS = ROOT / "src" / "coral_rag" / "static" / "map.css"


class MapProfileDrawerUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = MAP_HTML.read_text(encoding="utf-8")
        cls.javascript = MAP_JS.read_text(encoding="utf-8")
        cls.query_javascript = PROFILE_QUERY_JS.read_text(encoding="utf-8")
        cls.css = MAP_CSS.read_text(encoding="utf-8")

    def test_selection_uses_profile_api_only_after_a_marker_or_list_selection(self) -> None:
        select_body = self.javascript.split("function selectSite(site, origin) {", 1)[1].split(
            "function addMarker(site) {", 1
        )[0]
        load_body = self.javascript.split("async function loadSites() {", 1)[1].split(
            'elements.ednaForm.addEventListener("submit"', 1
        )[0]
        self.assertIn("loadSelectedSiteProfile();", select_body)
        self.assertNotIn("loadSelectedSiteProfile", load_body)
        self.assertNotIn("queryNearbyEdna(", select_body)
        self.assertNotIn("queryNearbyReefCheck(", select_body)
        self.assertNotIn("queryGeneralWeather(", select_body)
        self.assertIn('src="/static/dive-site-profile-query.js"', self.html)
        self.assertIn("fetch(profileTools.buildProfileUrl(context.siteId)", self.javascript)
        self.assertIn('cache: "no-store"', self.javascript)

    def test_profile_url_and_request_sequence_abort_stale_responses(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is unavailable for the browser helper contract test")
        script = r'''
const assert = require("assert");
const query = require("./src/coral_rag/static/dive-site-profile-query.js");
assert.strictEqual(
  query.buildProfileUrl("site / one"),
  "/api/dive-sites/site%20%2F%20one/profile"
);
assert.throws(() => query.buildProfileUrl(""), /site_id_required/);
const gate = new query.RequestCoordinator();
const first = gate.start({siteId: "first"});
const second = gate.start({siteId: "second"});
assert.strictEqual(first.signal.aborted, true);
assert.strictEqual(gate.isCurrent(first, {siteId: "first"}), false);
assert.strictEqual(gate.isCurrent(second, {siteId: "second"}), true);
gate.cancel();
assert.strictEqual(second.signal.aborted, true);
console.log(JSON.stringify({raceProtected: true}));
'''
        completed = subprocess.run(
            [node, "-e", script], cwd=ROOT, check=True, capture_output=True, text=True
        )
        self.assertTrue(json.loads(completed.stdout)["raceProtected"])
        self.assertIn("AbortError", self.javascript)
        self.assertIn("profileRequests.isCurrent(token, currentProfileContext())", self.javascript)

    def test_data_insufficient_and_all_safe_error_states_are_explicit(self) -> None:
        combined = self.html + self.javascript
        for text in (
            "地理／環境特色",
            "目前資料不足",
            "找不到目前選取潛點的介紹資料（404）",
            "潛點介紹來源目前無法驗證（503）",
            "無法連線至潛點介紹 API",
            "未顯示舊資料",
            "value.status === \"data_insufficient\"",
        ):
            with self.subTest(text=text):
                self.assertIn(text, combined)
        self.assertIn('role="status" aria-live="polite"', self.html)
        self.assertIn('aria-busy', self.javascript)

    def test_sources_fixed_limitations_and_safe_links_are_rendered_as_text(self) -> None:
        for text in (
            "維護單位",
            "最後核對日期",
            "授權／顯名",
            "來源限制",
            "開啟原始 HTTPS 來源",
            "僅限本機非商業研究模式",
        ):
            with self.subTest(text=text):
                self.assertIn(text, self.html + self.javascript)
        self.assertIn("renderProfileLimitations(payload, profile)", self.javascript)
        self.assertIn('id="profile-limitations"', self.html)
        self.assertIn('url.protocol === "https:"', self.javascript)
        self.assertIn('link.rel = "noopener noreferrer"', self.javascript)
        self.assertIn("textContent", self.javascript)
        self.assertNotIn("innerHTML", self.javascript)

    def test_desktop_drawer_mobile_bottom_panel_and_keyboard_controls_exist(self) -> None:
        self.assertIn('id="site-profile-drawer"', self.html)
        self.assertIn('id="profile-toggle"', self.html)
        self.assertIn('aria-controls="profile-drawer-content"', self.html)
        self.assertIn('aria-expanded="true"', self.html)
        self.assertIn(".profile-drawer", self.css)
        self.assertIn("@media (max-width: 760px)", self.css)
        self.assertIn(".profile-drawer { order: 0; }", self.css)
        self.assertIn("@media (max-width: 430px)", self.css)
        self.assertIn(".profile-drawer-heading { align-items: stretch; flex-direction: column; }", self.css)
        self.assertIn('elements.profileToggle.addEventListener("click"', self.javascript)
        self.assertIn("focusManualQuery(elements.ednaPanel", self.javascript)
        self.assertIn("focusManualQuery(elements.reefCheckPanel", self.javascript)
        self.assertIn("focusManualQuery(elements.weatherPanel", self.javascript)

    def test_local_media_block_has_safe_fallback_and_no_external_image_loading(self) -> None:
        combined = self.html + self.javascript
        self.assertIn('id="profile-media-state"', self.html)
        self.assertIn("renderProfileMedia(payload && payload.media)", self.javascript)
        self.assertIn("目前沒有可公開展示的官方圖片", combined)
        self.assertIn("/static/curated-media/dive-sites/", self.javascript)
        self.assertIn('img.addEventListener("error"', self.javascript)
        self.assertIn("未以其他圖片替代", self.javascript)
        self.assertIn("img.alt", self.javascript)
        self.assertNotIn("goocean", combined.lower())
        self.assertNotIn("innerHTML", self.javascript)
        self.assertIn(".profile-media img", self.css)
        self.assertIn("@media (max-width: 430px)", self.css)


if __name__ == "__main__":
    unittest.main()
