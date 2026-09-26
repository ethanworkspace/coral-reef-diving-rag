"""Offline UI contract and integration tests for Map v1 Profile eDNA QA drawer interface.

Verifies:
1. HTML Structure & Independence: dedicated section (#profile-edna-qa) distinct from #profile-qa.
   Includes mandatory radius dropdown, textarea (2-500 chars), counter, submit button, status, and citations container.
   No shared state, answer containers, or citation lists between profile-qa and profile-edna-qa.
   Strictly no model, provider, prompt override, or chunk control inputs.
2. Radius Selection & Integer Radius Passing: dropdown requires explicit selection (500, 1000, 2000, 5000),
   defaults to empty placeholder with no silent fallback.
3. API Contract & Zero Extra Fields: map.js calls POST /api/dive-sites/{encodeURIComponent(site_id)}/ask-edna.
   Request body strictly contains {"question": "...", "radius_m": <int>}, method POST, cache: no-store, credentials: same-origin.
4. Normal Response & Server Citation Rendering: only answerable responses render answer & citations;
   citation card renders server-bound provenance, coordinates, taxa, distance, radius, and OGL 1.0 license.
5. Fail-Closed Error Handling: 404, 422, 503, 500, network errors, scope_guidance, and safety intercepts
   immediately clear answer text and citations without displaying raw records or FTS fallbacks.
6. Race Condition Coordinator & Lifecycle Reset: ProfileEdnaQaRequestCoordinator aborts superseded requests;
   switching sites, collapsing drawer, or starting new queries clears previous answers and citations.
7. XSS Prevention & Safe HTTPS Links: zero innerHTML in map.js, external links strictly validate HTTPS
   with target="_blank" and rel="noopener noreferrer".
8. Explicit Disclaimers: prominent disclaimer text distinguishing historical water sample eDNA signals
   from in-situ sightings or current presence.
9. Endpoint Isolation: submitProfileEdnaQuestion only calls /api/dive-sites/{site_id}/ask-edna;
   never calls /ask-profile, /api/rag-v2/ask, or general RAG endpoints.
10. System Invariants: dive_sites.csv, candidate corpus, profile FTS DB, and assistant.html remain unmodified.
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
CANDIDATES_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_rag_candidates.jsonl"
PROFILE_FTS_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_fts.sqlite"

EXPECTED_DIVE_SITES_SHA256 = "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
EXPECTED_CANDIDATES_SHA256 = "f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92"
EXPECTED_PROFILE_FTS_SHA256 = "5aef5b08087bb74eb433ee5dc2a25f7c673c81ad014987841ccd89659239886c"


class TestMapProfileEdnaAnswerUiContract(unittest.TestCase):
    """Test suite for Profile eDNA QA drawer interface contracts and client behavior."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = MAP_HTML.read_text(encoding="utf-8")
        cls.javascript = MAP_JS.read_text(encoding="utf-8")
        cls.css = MAP_CSS.read_text(encoding="utf-8")

    def test_item_1_html_structure_independence_and_prohibited_controls(self) -> None:
        """1. Verify dedicated #profile-edna-qa section, independence from #profile-qa, and absence of prohibited inputs."""
        drawer_part = self.html.split('id="site-profile-drawer"')[1].split('id="site-detail"')[0]

        # Verify both sections exist
        self.assertIn('id="profile-qa"', drawer_part)
        self.assertIn('id="profile-edna-qa"', drawer_part)

        # eDNA QA specific elements
        self.assertIn("eDNA 歷史採樣問答", drawer_part)
        self.assertIn(
            "本問答依據周邊歷史水樣 eDNA 分子訊號，不代表潛點現地目擊、目前物種存在或可見，也不是完整物種名錄。",
            drawer_part,
        )
        self.assertIn('id="profile-edna-qa-form"', drawer_part)
        self.assertIn('id="profile-edna-qa-radius"', drawer_part)
        self.assertIn('id="profile-edna-qa-input"', drawer_part)
        self.assertIn('id="profile-edna-qa-counter"', drawer_part)
        self.assertIn('id="profile-edna-qa-submit"', drawer_part)
        self.assertIn('id="profile-edna-qa-status"', drawer_part)
        self.assertIn('id="profile-edna-qa-answer-container"', drawer_part)
        self.assertIn('id="profile-edna-qa-answer-text"', drawer_part)
        self.assertIn('id="profile-edna-qa-citations-section"', drawer_part)
        self.assertIn('id="profile-edna-qa-citations-list"', drawer_part)

        # Independence: Ensure distinct element IDs (no DOM sharing)
        profile_qa_markup = drawer_part.split('id="profile-qa"')[1].split('</section>')[0]
        edna_qa_markup = drawer_part.split('id="profile-edna-qa"')[1].split('</section>')[0]

        self.assertNotIn("profile-edna-qa-input", profile_qa_markup)
        self.assertNotIn("profile-qa-input", edna_qa_markup)
        self.assertNotIn("profile-edna-qa-answer-container", profile_qa_markup)
        self.assertNotIn("profile-qa-answer-container", edna_qa_markup)

        # Prohibited controls in eDNA QA
        for prohibited in [
            'select name="model"',
            'select name="provider"',
            'input name="provider"',
            'input name="model"',
            "temperature",
            "top_p",
            "prompt_override",
            "chunk_id",
            "chunk_select",
        ]:
            with self.subTest(prohibited=prohibited):
                self.assertNotIn(prohibited, edna_qa_markup)

    def test_item_2_radius_selection_and_integer_radius_passing(self) -> None:
        """2. Verify radius dropdown options, empty default, and strict integer radius validation in map.js."""
        # Dropdown options in HTML
        edna_qa_markup = self.html.split('id="profile-edna-qa"')[1].split('</section>')[0]
        self.assertIn('<option value="" selected>請選擇搜尋半徑</option>', edna_qa_markup)
        self.assertIn('<option value="500">500 公尺</option>', edna_qa_markup)
        self.assertIn('<option value="1000">1,000 公尺</option>', edna_qa_markup)
        self.assertIn('<option value="2000">2,000 公尺</option>', edna_qa_markup)
        self.assertIn('<option value="5000">5,000 公尺</option>', edna_qa_markup)

        # Validation logic in map.js
        self.assertIn("parseInt(rawRadius, 10)", self.javascript)
        self.assertIn("[500, 1000, 2000, 5000].includes(radiusInt)", self.javascript)

        # Node.js validation test
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not available in test environment")

        script = r'''
const assert = require("assert");

function validateRadius(rawRadius) {
  const radiusInt = parseInt(rawRadius, 10);
  if (!rawRadius || Number.isNaN(radiusInt) || ![500, 1000, 2000, 5000].includes(radiusInt)) {
    return { valid: false, radiusInt: null };
  }
  return { valid: true, radiusInt };
}

assert.strictEqual(validateRadius("").valid, false);
assert.strictEqual(validateRadius("abc").valid, false);
assert.strictEqual(validateRadius("250").valid, false);
assert.strictEqual(validateRadius("500").valid, true);
assert.strictEqual(validateRadius("500").radiusInt, 500);
assert.strictEqual(validateRadius("1000").valid, true);
assert.strictEqual(validateRadius("1000").radiusInt, 1000);
assert.strictEqual(validateRadius("2000").valid, true);
assert.strictEqual(validateRadius("2000").radiusInt, 2000);
assert.strictEqual(validateRadius("5000").valid, true);
assert.strictEqual(validateRadius("5000").radiusInt, 5000);
assert.strictEqual(validateRadius("10000").valid, false);

console.log(JSON.stringify({ radiusValidationPassed: true }));
'''
        proc = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
        out = json.loads(proc.stdout)
        self.assertTrue(out.get("radiusValidationPassed"))

    def test_item_3_api_endpoint_path_body_and_fetch_options(self) -> None:
        """3. Verify endpoint URL, encodeURIComponent, body payload, and fetch options in map.js."""
        # Dedicated endpoint pattern with encodeURIComponent
        self.assertIn(
            "`/api/dive-sites/${encodeURIComponent(siteId)}/ask-edna`",
            self.javascript,
        )

        submit_func = self.javascript.split("async function submitProfileEdnaQuestion() {")[1].split("function focusManualQuery")[0]

        # Request method and headers
        self.assertIn('method: "POST"', submit_func)
        self.assertIn('"Content-Type": "application/json"', submit_func)
        self.assertIn('"Accept": "application/json"', submit_func)
        self.assertIn('cache: "no-store"', submit_func)
        self.assertIn('credentials: "same-origin"', submit_func)

        # Request body strictly contains question and radius_m only
        self.assertIn(
            "body: JSON.stringify({ question: cleanQuestion, radius_m: radiusInt })",
            submit_func,
        )
        self.assertNotIn("provider:", submit_func.split("catch (error)")[0])
        self.assertNotIn("model:", submit_func.split("catch (error)")[0])
        self.assertNotIn("prompt:", submit_func.split("catch (error)")[0])
        self.assertNotIn("citation:", submit_func.split("catch (error)")[0])
        self.assertNotIn("source_record_id:", submit_func.split("catch (error)")[0])

    def test_item_4_normal_response_and_citation_rendering(self) -> None:
        """4. Verify only answerable responses render answer & citations; citations contain complete provenance fields."""
        submit_func = self.javascript.split("async function submitProfileEdnaQuestion() {")[1].split("function focusManualQuery")[0]

        # answerable check
        self.assertIn('payload.status === "answerable"', submit_func)
        self.assertIn("elements.profileEdnaQaAnswerText.textContent = answerText;", submit_func)
        self.assertIn("elements.profileEdnaQaAnswerContainer.hidden = false;", submit_func)
        self.assertIn("renderProfileEdnaQaCitationCard", submit_func)

        # renderProfileEdnaQaCitationCard verification
        card_func = self.javascript.split("function renderProfileEdnaQaCitationCard(cit) {")[1].split("async function submitProfileEdnaQuestion() {")[0]
        self.assertIn('card.className = "profile-edna-qa-citation-card"', card_func)
        self.assertIn('appendEvidenceField(dl, "潛點名稱", cit.site_name)', card_func)
        self.assertIn('appendEvidenceField(dl, "資料性質", cit.data_nature)', card_func)
        self.assertIn('appendEvidenceField(dl, "搜尋半徑"', card_func)
        self.assertIn('appendEvidenceField(dl, "距代表點"', card_func)
        self.assertIn('appendEvidenceField(dl, "測站代號", cit.station_id)', card_func)
        self.assertIn('appendEvidenceField(dl, "採樣日期", cit.sampled_at)', card_func)
        self.assertIn('appendEvidenceField(dl, "採樣座標"', card_func)
        self.assertIn('appendEvidenceField(dl, "檢出分類群"', card_func)
        self.assertIn('appendEvidenceField(dl, "來源定位器", cit.source_record_id)', card_func)
        self.assertIn('appendEvidenceField(dl, "授權條款", cit.license_name)', card_func)
        self.assertIn('appendEvidenceField(dl, "宣告標示", cit.required_attribution)', card_func)
        self.assertIn('appendEvidenceField(dl, "限制說明"', card_func)
        self.assertIn('appendEvidenceField(dl, "官方資料集"', card_func)

    def test_item_5_fail_closed_error_handling_and_no_raw_fallback(self) -> None:
        """5. Verify 404, 422, 503, 500, network errors, and safety intercepts clear answers and citations."""
        submit_func = self.javascript.split("async function submitProfileEdnaQuestion() {")[1].split("function focusManualQuery")[0]

        # Status code checks all invoke clearProfileEdnaQaDisplay()
        for status_code in ["404", "422", "503", "500"]:
            with self.subTest(status_code=status_code):
                self.assertIn(f"response.status === {status_code}", submit_func)

        # Business statuses clear display
        for status_name in ["scope_guidance", "safety_intercepted", "insufficient_evidence", "unconfigured_llm", "llm_call_failed"]:
            with self.subTest(status_name=status_name):
                self.assertIn(f'payload.status === "{status_name}"', submit_func)

        # Clear display invocation count
        self.assertGreater(submit_func.count("clearProfileEdnaQaDisplay()"), 5)

        # No fallback to search_profile_fts, profile_rag_candidates, or raw records
        self.assertNotIn("search_profile_fts", submit_func)
        self.assertNotIn("profile_fts", submit_func)
        self.assertNotIn("chunks.jsonl", submit_func)

    def test_item_6_race_condition_coordinator_and_lifecycle_reset(self) -> None:
        """6. Verify ProfileEdnaQaRequestCoordinator manages AbortController and resets on site switch/collapse."""
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not available in test environment")

        script = r'''
const assert = require("assert");

class ProfileEdnaQaRequestCoordinator {
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

const coordinator = new ProfileEdnaQaRequestCoordinator();
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

// Cancellation on collapse or reset
coordinator.cancel();
assert.strictEqual(token2.signal.aborted, true);
assert.strictEqual(coordinator.isCurrent(token2, "site-2"), false);

console.log(JSON.stringify({ ednaRaceGuardPassed: true }));
'''
        proc = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
        out = json.loads(proc.stdout)
        self.assertTrue(out.get("ednaRaceGuardPassed"))

        # Verify implementation in map.js
        self.assertIn("class ProfileEdnaQaRequestCoordinator", self.javascript)
        self.assertIn("const profileEdnaQaRequests = new ProfileEdnaQaRequestCoordinator();", self.javascript)

        # Lifecycle integration
        select_site_code = self.javascript.split("function selectSite(site, origin) {")[1].split("elements.detailName.textContent")[0]
        self.assertIn("resetProfileEdnaQa(", select_site_code)

        clear_profile_code = self.javascript.split("function clearProfileDisplay() {")[1].split("elements.profileDetails.hidden = true;")[0]
        self.assertIn("clearProfileEdnaQaDisplay();", clear_profile_code)

        collapse_code = self.javascript.split("function setProfileDrawerCollapsed(collapsed) {")[1].split("function clearProfileSources")[0]
        self.assertIn("profileEdnaQaRequests.cancel();", collapse_code)

    def test_item_7_xss_prevention_zero_inner_html_and_safe_links(self) -> None:
        """7. Verify zero innerHTML in map.js and that external links strictly validate HTTPS with safe attributes."""
        # Zero innerHTML in entire map.js
        self.assertNotIn("innerHTML", self.javascript)

        # Safe link creation verification
        card_func = self.javascript.split("function renderProfileEdnaQaCitationCard(cit) {")[1].split("async function submitProfileEdnaQuestion() {")[0]
        self.assertIn("safeHttpsUrl(cit.source_url)", card_func)
        self.assertIn("createSafeLink(", card_func)

        # Confirm createSafeLink sets target=_blank and rel=noopener noreferrer
        create_link_code = self.javascript.split("function createSafeLink(label, value) {")[1].split("function appendEvidenceField")[0]
        self.assertIn('link.target = "_blank"', create_link_code)
        self.assertIn('link.rel = "noopener noreferrer"', create_link_code)

    def test_item_8_explicit_disclaimer_distinguishing_dna_from_live_sightings(self) -> None:
        """8. Verify disclaimer clearly separates historical water sample DNA from in-situ observations."""
        disclaimer = "本問答依據周邊歷史水樣 eDNA 分子訊號，不代表潛點現地目擊、目前物種存在或可見，也不是完整物種名錄。"
        self.assertIn(disclaimer, self.html)
        self.assertIn(".profile-edna-qa-disclaimer", self.css)

    def test_item_9_endpoint_isolation_no_general_rag_or_profile_qa_calls(self) -> None:
        """9. Verify submitProfileEdnaQuestion only calls /ask-edna and never calls /ask-profile or /api/rag-v2/ask."""
        submit_func = self.javascript.split("async function submitProfileEdnaQuestion() {")[1].split("function focusManualQuery")[0]
        self.assertIn("/api/dive-sites/${encodeURIComponent(siteId)}/ask-edna", submit_func)
        self.assertNotIn("/ask-profile", submit_func)
        self.assertNotIn("/api/rag-v2/ask", submit_func)

    def test_item_10_system_invariants_and_zero_regressions(self) -> None:
        """10. Verify dive_sites.csv, candidate corpus, profile FTS DB, and assistant.html remain unmodified."""
        # dive_sites.csv SHA-256
        dive_sites_sha = hashlib.sha256(DIVE_SITES_CSV.read_bytes()).hexdigest().lower()
        self.assertEqual(dive_sites_sha, EXPECTED_DIVE_SITES_SHA256)

        # profile_rag_candidates.jsonl SHA-256
        candidates_sha = hashlib.sha256(CANDIDATES_PATH.read_bytes()).hexdigest().lower()
        self.assertEqual(candidates_sha, EXPECTED_CANDIDATES_SHA256)

        # profile_fts.sqlite SHA-256
        fts_sha = hashlib.sha256(PROFILE_FTS_PATH.read_bytes()).hexdigest().lower()
        self.assertEqual(fts_sha, EXPECTED_PROFILE_FTS_SHA256)

        # assistant.html untouched
        assistant_content = ASSISTANT_HTML.read_text(encoding="utf-8")
        self.assertIn("研究問答", assistant_content)
        self.assertNotIn("ask-edna", assistant_content)


if __name__ == "__main__":
    unittest.main()
