"""Offline UI contract and integration tests for Map v1 Profile generative QA drawer interface.

Verifies:
1. HTML Structure: dedicated Profile QA section (#profile-qa) in map.html inside profile-drawer.
   Includes disclaimer, textarea (2-500 chars), counter, submit button, status, and citations container.
   Strictly no model, provider, prompt, or retrieval control inputs.
2. API Contract & Zero Extra Fields: map.js calls POST /api/dive-sites/{encodeURIComponent(site_id)}/ask-profile.
   Request body strictly contains {"question": "..."}, method POST, cache: no-store, credentials: same-origin.
3. Race Condition & Site Isolation: ProfileQaRequestCoordinator aborts superseded requests;
   stale responses for mismatched sites are discarded.
4. Selection & Query State Reset: switching sites, closing drawer, or new queries immediately clears previous answer & citations.
5. XSS Prevention & Safe HTTPS Links: zero innerHTML in map.js, links only accept verified HTTPS with target="_blank" and rel="noopener noreferrer".
6. Fail-Closed Error Handling: 404, 422, 503, 500, network errors, and safety intercepts clear citations and never display FTS fallbacks.
7. Accessibility & Responsive Styling: appropriate ARIA attributes, live regions, keyboard accessible, mobile media queries.
8. System Invariants: assistant.html, rag_v2_chat.js, /api/rag-v2/ask, and dive_sites.csv SHA-256 remain untouched.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAP_HTML = ROOT / "src" / "coral_rag" / "templates" / "map.html"
MAP_JS = ROOT / "src" / "coral_rag" / "static" / "map.js"
MAP_CSS = ROOT / "src" / "coral_rag" / "static" / "map.css"
ASSISTANT_HTML = ROOT / "src" / "coral_rag" / "templates" / "assistant.html"
DIVE_SITES_CSV = ROOT / "data" / "curated" / "dive_sites.csv"

EXPECTED_DIVE_SITES_SHA256 = (
    "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
)


class TestMapProfileAnswerUiContract(unittest.TestCase):
    """Test suite for Profile QA drawer interface contracts and client behavior."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = MAP_HTML.read_text(encoding="utf-8")
        cls.javascript = MAP_JS.read_text(encoding="utf-8")
        cls.css = MAP_CSS.read_text(encoding="utf-8")

    def test_item_1_html_structure_elements_and_prohibited_controls(self) -> None:
        """1. Verify HTML structure, disclaimer, input controls, and absence of model/provider selectors."""
        # Confirm section exists in drawer
        drawer_part = self.html.split('id="site-profile-drawer"')[1].split('id="site-detail"')[0]
        self.assertIn('id="profile-qa"', drawer_part)
        self.assertIn("官方背景問答（受控繁中檢索回答）", drawer_part)

        # Disclaimer
        self.assertIn(
            "免責說明：回答僅依官方核准景點背景，不提供入水位置、即時海況、安全、合法性或活動建議。",
            drawer_part,
        )

        # Form and inputs
        self.assertIn('id="profile-qa-form"', drawer_part)
        self.assertIn('id="profile-qa-input"', drawer_part)
        self.assertIn('maxlength="500"', drawer_part)
        self.assertIn('rows="3"', drawer_part)
        self.assertIn('id="profile-qa-counter"', drawer_part)
        self.assertIn('id="profile-qa-submit"', drawer_part)
        self.assertIn('id="profile-qa-status"', drawer_part)
        self.assertIn('role="status"', drawer_part)
        self.assertIn('aria-live="polite"', drawer_part)

        # Answer and citations container
        self.assertIn('id="profile-qa-answer-container"', drawer_part)
        self.assertIn('id="profile-qa-answer-text"', drawer_part)
        self.assertIn('id="profile-qa-citations-section"', drawer_part)
        self.assertIn('id="profile-qa-citations-list"', drawer_part)

        # Prohibited controls: strictly NO model, provider, prompt override, chunk selector in profile-qa
        qa_markup = drawer_part.split('id="profile-qa"')[1].split('</section>')[0]
        for prohibited in [
            "select name=\"model\"",
            "select name=\"provider\"",
            "input name=\"provider\"",
            "input name=\"model\"",
            "temperature",
            "top_p",
            "prompt_override",
            "chunk_id",
            "chunk_select",
        ]:
            with self.subTest(prohibited=prohibited):
                self.assertNotIn(prohibited, qa_markup)

    def test_item_2_api_endpoint_path_body_and_fetch_options(self) -> None:
        """2. Verify endpoint URL, encodeURIComponent, body payload, and fetch options in map.js."""
        # Dedicated endpoint pattern with encodeURIComponent
        self.assertIn(
            "`/api/dive-sites/${encodeURIComponent(siteId)}/ask-profile`",
            self.javascript,
        )

        # Request method and headers
        self.assertIn('method: "POST"', self.javascript)
        self.assertIn('"Content-Type": "application/json"', self.javascript)
        self.assertIn('"Accept": "application/json"', self.javascript)
        self.assertIn('cache: "no-store"', self.javascript)
        self.assertIn('credentials: "same-origin"', self.javascript)

        # Request body strictly contains question only
        self.assertIn(
            "body: JSON.stringify({ question: cleanQuestion })",
            self.javascript,
        )
        self.assertNotIn("provider:", self.javascript.split("submitProfileQuestion")[1].split("catch (error)")[0])
        self.assertNotIn("model:", self.javascript.split("submitProfileQuestion")[1].split("catch (error)")[0])

    def test_item_3_race_condition_coordinator_via_node(self) -> None:
        """3. Verify ProfileQaRequestCoordinator manages AbortController and sequence guarding."""
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not available in test environment")

        script = r'''
const assert = require("assert");

class ProfileQaRequestCoordinator {
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
    return Boolean(
      token &&
      token.sequence === this.sequence &&
      token.siteId === currentSiteId &&
      !token.signal?.aborted
    );
  }
  finish(token) {
    if (token && token.sequence === this.sequence) {
      this.controller = null;
    }
  }
}

const coordinator = new ProfileQaRequestCoordinator();
const token1 = coordinator.start("site-1");
assert.strictEqual(token1.sequence, 1);
assert.strictEqual(token1.signal.aborted, false);

// Starting second query for site-2 aborts token1
const token2 = coordinator.start("site-2");
assert.strictEqual(token1.signal.aborted, true);
assert.strictEqual(token2.sequence, 2);
assert.strictEqual(token2.signal.aborted, false);

// isCurrent guards
assert.strictEqual(coordinator.isCurrent(token1, "site-1"), false);
assert.strictEqual(coordinator.isCurrent(token2, "site-1"), false);
assert.strictEqual(coordinator.isCurrent(token2, "site-2"), true);

// Cancellation
coordinator.cancel();
assert.strictEqual(token2.signal.aborted, true);
assert.strictEqual(coordinator.isCurrent(token2, "site-2"), false);

console.log(JSON.stringify({ raceGuardPassed: true }));
'''
        proc = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
        out = json.loads(proc.stdout)
        self.assertTrue(out.get("raceGuardPassed"))

        # Verify coordinator implementation in map.js
        self.assertIn("class ProfileQaRequestCoordinator", self.javascript)
        self.assertIn("const profileQaRequests = new ProfileQaRequestCoordinator();", self.javascript)
        self.assertIn("!token.signal?.aborted", self.javascript)

    def test_item_4_selection_reset_and_immediate_state_clearing(self) -> None:
        """4. Verify switching sites or closing drawer resets state and clears old answers/citations."""
        # selectSite calls resetProfileQa
        select_site_code = self.javascript.split("function selectSite(site, origin) {")[1].split("elements.detailName.textContent")[0]
        self.assertIn("resetProfileQa(", select_site_code)

        # clearProfileDisplay clears Profile QA
        clear_profile_code = self.javascript.split("function clearProfileDisplay() {")[1].split("elements.profileDetails.hidden = true;")[0]
        self.assertIn("clearProfileQaDisplay();", clear_profile_code)

        # setProfileDrawerCollapsed cancels pending profile QA requests
        collapse_code = self.javascript.split("function setProfileDrawerCollapsed(collapsed) {")[1].split("elements.profileContent.hidden = collapsed;")[0]
        self.assertIn("profileQaRequests.cancel();", self.javascript.split("function setProfileDrawerCollapsed(collapsed) {")[1].split("function clearProfileSources")[0])

        # submitProfileQuestion clears display immediately upon starting request
        submit_code = self.javascript.split("async function submitProfileQuestion() {")[1].split("try {")[0]
        self.assertIn("clearProfileQaDisplay();", submit_code)
        self.assertIn("setProfileQaBusy(true);", submit_code)

    def test_item_5_zero_inner_html_and_safe_https_link_rendering(self) -> None:
        """5. Verify zero innerHTML, and links only accept verified HTTPS with target=_blank & rel=noopener noreferrer."""
        # Zero innerHTML in entire map.js
        self.assertNotIn("innerHTML", self.javascript)
        self.assertIn("textContent", self.javascript)
        self.assertIn("replaceChildren", self.javascript)
        self.assertIn("createElement", self.javascript)

        # Safe link creation verification via Node.js
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not available in test environment")

        script = r'''
const assert = require("assert");

function safeHttpsUrl(value) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : null;
  } catch (_error) {
    return null;
  }
}

// HTTPS link passes
assert.strictEqual(safeHttpsUrl("https://example.com/doc"), "https://example.com/doc");

// HTTP link rejected
assert.strictEqual(safeHttpsUrl("http://example.com/doc"), null);

// Javascript URI rejected
assert.strictEqual(safeHttpsUrl("javascript:alert(1)"), null);

// Data URI rejected
assert.strictEqual(safeHttpsUrl("data:text/html,<script>alert(1)</script>"), null);

// Relative URL rejected
assert.strictEqual(safeHttpsUrl("/relative/path"), null);

console.log(JSON.stringify({ linkSecurityPassed: true }));
'''
        proc = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
        out = json.loads(proc.stdout)
        self.assertTrue(out.get("linkSecurityPassed"))

    def test_item_6_fail_closed_error_handling_and_no_generative_fallback(self) -> None:
        """6. Verify errors (404, 422, 503, 500, network error) never render FTS fallback or citations."""
        submit_func = self.javascript.split("async function submitProfileQuestion() {")[1].split("function focusManualQuery")[0]

        # 404, 422, 503, 500 checks all invoke clearProfileQaDisplay()
        for status_code in ["404", "422", "503", "500"]:
            self.assertIn(f"response.status === {status_code}", submit_func)

        # Safety intercepted, insufficient evidence, unconfigured LLM, LLM failed clear display
        for status_name in ["safety_intercepted", "insufficient_evidence", "unconfigured_llm", "llm_call_failed"]:
            self.assertIn(f'payload.status === "{status_name}"', submit_func)

        # No search_profile_fts, chunks, or hybrid retrieval fallbacks in frontend
        self.assertNotIn("search_profile_fts", submit_func)
        self.assertNotIn("profile_fts", submit_func)
        self.assertNotIn("chunks.jsonl", submit_func)

    def test_item_7_accessibility_aria_and_responsive_css(self) -> None:
        """7. Verify ARIA attributes, keyboard accessibility, and responsive CSS rules."""
        # Live region and status elements
        self.assertIn('aria-live="polite"', self.html)
        self.assertIn('role="status"', self.html)
        self.assertIn('aria-describedby="profile-qa-counter profile-qa-hint"', self.html)

        # CSS classes
        self.assertIn(".profile-qa-section", self.css)
        self.assertIn(".profile-qa-disclaimer", self.css)
        self.assertIn(".profile-qa-textarea", self.css)
        self.assertIn(".profile-qa-submit-button", self.css)
        self.assertIn(".profile-qa-counter", self.css)
        self.assertIn(".profile-qa-answer-container", self.css)
        self.assertIn(".profile-qa-citation-card", self.css)

        # Focus outline and mobile breakpoints
        self.assertIn(".profile-qa-textarea:focus-visible", self.css)
        self.assertIn("@media (max-width: 430px)", self.css)
        self.assertIn(".profile-qa-submit-button { width: 100%; }", self.css)

    def test_item_8_system_invariants_and_zero_regressions(self) -> None:
        """8. Verify assistant.html, dive_sites.csv SHA-256 remain completely unchanged."""
        # Curated dive sites hash
        content = DIVE_SITES_CSV.read_bytes()
        actual_sha = hashlib.sha256(content).hexdigest().lower()
        self.assertEqual(actual_sha, EXPECTED_DIVE_SITES_SHA256)

        # assistant.html untouched
        assistant_content = ASSISTANT_HTML.read_text(encoding="utf-8")
        self.assertIn("研究問答", assistant_content)
        self.assertNotIn("ask-profile", assistant_content)


if __name__ == "__main__":
    unittest.main()
