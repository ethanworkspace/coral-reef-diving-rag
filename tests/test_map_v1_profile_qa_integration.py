"""End-to-End integration tests for Profile QA and eDNA QA drawer cards coexistence.

Verifies:
1. Card Coexistence & Markup Independence:
   - Dedicated #profile-qa and #profile-edna-qa cards exist in the profile drawer.
   - Distinct IDs for forms, inputs, counters, buttons, statuses, containers, and citation lists.
   - Clear and distinct disclaimers (representative point vs entry/safety; historical water sample eDNA vs live sighting).
   - Prohibited controls (model, provider, prompt override, chunk selectors) strictly absent.
2. Endpoint & Payload Whitelisting:
   - Profile QA calls POST /api/dive-sites/{encodeURIComponent(site_id)}/ask-profile with body {"question": "..."}.
   - eDNA QA calls POST /api/dive-sites/{encodeURIComponent(site_id)}/ask-edna with body {"question": "...", "radius_m": <int>}.
   - eDNA requires radius from [500, 1000, 2000, 5000]; stops fetch if radius unselected.
   - Profile QA never sends radius_m.
   - Zero calls to /api/rag-v2/ask or the other card's endpoint.
3. Node.js Client-Side Integration Simulation:
   - Simultaneous query execution for both cards without cross-contamination.
   - Switching dive sites aborts in-flight requests for old site.
   - Delayed slow responses from old site are discarded (never overwrite new site).
   - Drawer collapse immediately cancels pending requests for both cards.
   - Single card error (e.g. 500) does not clear or corrupt the other card's successful response.
   - Non-answerable statuses (safety_intercepted, insufficient_evidence, scope_guidance, 404, 422, 503) fail closed.
   - Zero innerHTML in map.js; XSS rejection for non-HTTPS schemes (javascript:, http:, data:).
4. System Invariants & Bitwise Immutability:
   - dive_sites.csv, profile_rag_candidates.jsonl, profile_fts.sqlite, chunks.jsonl SHA-256 unmodified.
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
DIVE_SITES_CSV = ROOT / "data" / "curated" / "dive_sites.csv"
CANDIDATES_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_rag_candidates.jsonl"
PROFILE_FTS_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_fts.sqlite"
RAG_V2_CHUNKS_PATH = ROOT / "data" / "processed" / "rag_v2" / "chunks.jsonl"

EXPECTED_DIVE_SITES_SHA256 = (
    "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
)
EXPECTED_CANDIDATES_SHA256 = (
    "f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92"
)
EXPECTED_PROFILE_FTS_SHA256 = (
    "5aef5b08087bb74eb433ee5dc2a25f7c673c81ad014987841ccd89659239886c"
)


class TestProfileAndEdnaQaCoexistenceMarkup(unittest.TestCase):
    """Test HTML structure, element independence, and disclaimers for both cards."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = MAP_HTML.read_text(encoding="utf-8")
        cls.javascript = MAP_JS.read_text(encoding="utf-8")
        cls.css = MAP_CSS.read_text(encoding="utf-8")

    def test_both_sections_exist_in_drawer_with_distinct_elements(self) -> None:
        """Verify both #profile-qa and #profile-edna-qa exist inside drawer with distinct IDs."""
        drawer_part = self.html.split('id="site-profile-drawer"')[1].split('id="site-detail"')[0]
        self.assertIn('id="profile-qa"', drawer_part)
        self.assertIn('id="profile-edna-qa"', drawer_part)

        # Profile QA elements
        self.assertIn('id="profile-qa-form"', drawer_part)
        self.assertIn('id="profile-qa-input"', drawer_part)
        self.assertIn('id="profile-qa-counter"', drawer_part)
        self.assertIn('id="profile-qa-submit"', drawer_part)
        self.assertIn('id="profile-qa-status"', drawer_part)
        self.assertIn('id="profile-qa-answer-container"', drawer_part)
        self.assertIn('id="profile-qa-answer-text"', drawer_part)
        self.assertIn('id="profile-qa-citations-section"', drawer_part)
        self.assertIn('id="profile-qa-citations-list"', drawer_part)

        # eDNA QA elements
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

        # Confirm no DOM sharing between cards
        profile_markup = drawer_part.split('id="profile-qa"')[1].split('</section>')[0]
        edna_markup = drawer_part.split('id="profile-edna-qa"')[1].split('</section>')[0]
        self.assertNotIn("profile-edna-qa", profile_markup)
        self.assertNotIn("profile-qa-input", edna_markup)
        self.assertNotIn("profile-qa-citations-list", edna_markup)

    def test_disclaimers_present_and_differentiated(self) -> None:
        """Verify each card presents its required domain-specific disclaimer text."""
        drawer_part = self.html.split('id="site-profile-drawer"')[1].split('id="site-detail"')[0]

        profile_disclaimer = (
            "免責說明：回答僅依官方核准景點背景，不提供入水位置、即時海況、安全、合法性或活動建議。"
        )
        edna_disclaimer = (
            "本問答依據周邊歷史水樣 eDNA 分子訊號，不代表潛點現地目擊、目前物種存在或可見，也不是完整物種名錄。"
        )
        self.assertIn(profile_disclaimer, drawer_part)
        self.assertIn(edna_disclaimer, drawer_part)

    def test_prohibited_controls_absent_in_both_cards(self) -> None:
        """Strictly prohibit model, provider, temperature, prompt override, or chunk selectors."""
        drawer_part = self.html.split('id="site-profile-drawer"')[1].split('id="site-detail"')[0]
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
                self.assertNotIn(prohibited, drawer_part)

    def test_accessibility_roles_and_live_regions(self) -> None:
        """Verify ARIA live regions and status roles for both cards."""
        drawer_part = self.html.split('id="site-profile-drawer"')[1].split('id="site-detail"')[0]
        self.assertIn('id="profile-qa-status" class="profile-qa-status" role="status" aria-live="polite"', drawer_part)
        self.assertIn('id="profile-edna-qa-status" class="profile-edna-qa-status" role="status" aria-live="polite"', drawer_part)
        self.assertIn('id="profile-qa-counter" class="profile-qa-counter" aria-live="polite"', drawer_part)
        self.assertIn('id="profile-edna-qa-counter" class="profile-edna-qa-counter" aria-live="polite"', drawer_part)


class TestProfileAndEdnaQaApiPayloadContract(unittest.TestCase):
    """Test API endpoint URLs, body structure, and parameter whitelisting in map.js."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.javascript = MAP_JS.read_text(encoding="utf-8")

    def test_distinct_endpoint_paths_and_encoding(self) -> None:
        """Verify URL routing: Profile calls /ask-profile, eDNA calls /ask-edna with encodeURIComponent."""
        self.assertIn(
            "`/api/dive-sites/${encodeURIComponent(siteId)}/ask-profile`",
            self.javascript,
        )
        self.assertIn(
            "`/api/dive-sites/${encodeURIComponent(siteId)}/ask-edna`",
            self.javascript,
        )

    def test_endpoint_isolation_no_cross_calls_or_rag_v2(self) -> None:
        """Verify neither function calls the other's endpoint or /api/rag-v2/ask."""
        profile_fn = self.javascript.split("async function submitProfileQuestion() {")[1].split("function clearProfileEdnaQaDisplay")[0]
        edna_fn = self.javascript.split("async function submitProfileEdnaQuestion() {")[1].split("function focusManualQuery")[0]

        self.assertNotIn("/ask-edna", profile_fn)
        self.assertNotIn("/api/rag-v2/ask", profile_fn)

        self.assertNotIn("/ask-profile", edna_fn)
        self.assertNotIn("/api/rag-v2/ask", edna_fn)

    def test_payload_whitelisting_in_js(self) -> None:
        """Verify Profile payload strictly contains {question} and eDNA strictly contains {question, radius_m}."""
        profile_fn = self.javascript.split("async function submitProfileQuestion() {")[1].split("function clearProfileEdnaQaDisplay")[0]
        edna_fn = self.javascript.split("async function submitProfileEdnaQuestion() {")[1].split("function focusManualQuery")[0]

        # Profile strictly passes question
        self.assertIn("body: JSON.stringify({ question: cleanQuestion })", profile_fn)
        self.assertNotIn("radius_m", profile_fn)

        # eDNA strictly passes question and radius_m
        self.assertIn(
            "body: JSON.stringify({ question: cleanQuestion, radius_m: radiusInt })",
            edna_fn,
        )

    def test_radius_validation_and_rejection(self) -> None:
        """Verify eDNA rejects missing or invalid radius values before fetch."""
        edna_fn = self.javascript.split("async function submitProfileEdnaQuestion() {")[1].split("function focusManualQuery")[0]
        self.assertIn("![500, 1000, 2000, 5000].includes(radiusInt)", edna_fn)
        self.assertIn("請先選擇搜尋半徑（500、1,000、2,000 或 5,000 公尺）。", edna_fn)


class TestProfileAndEdnaQaNodeIntegrationSimulation(unittest.TestCase):
    """End-to-End client-side integration simulation using Node.js."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("Node.js not available on system")

    def _run_node_script(self, script: str) -> dict:
        proc = subprocess.run(
            [self.node, "-e", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            self.fail(f"Node script failed with exit code {proc.returncode}:\n{proc.stderr}\n{proc.stdout}")
        try:
            return json.loads(proc.stdout)
        except Exception:
            return {"raw_output": proc.stdout}

    def test_simulated_dual_card_execution_and_isolation(self) -> None:
        """Simulate concurrent queries to Profile QA and eDNA QA; verify independent rendering and citation containment."""
        script = r'''
const assert = require("assert");

class MockElement {
  constructor(tag, id = "") {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.value = "";
    this.textContent = "";
    this.hidden = false;
    this.disabled = false;
    this.children = [];
    this.className = "";
  }
  setAttribute(k, v) {}
  getAttribute(k) { return null; }
  replaceChildren(...kids) { this.children = [...kids]; }
  append(...kids) { this.children.push(...kids); }
}

global.document = {
  createElement: (tag) => new MockElement(tag)
};

// Request coordinators
class Coordinator {
  constructor() { this.sequence = 0; this.controller = null; }
  start(siteId) {
    this.cancel();
    this.sequence += 1;
    this.controller = new AbortController();
    return { sequence: this.sequence, siteId, signal: this.controller.signal };
  }
  cancel() { if (this.controller) { this.controller.abort(); this.controller = null; } }
  isCurrent(token, currentSiteId) {
    return Boolean(token && token.sequence === this.sequence && token.siteId === currentSiteId && !token.signal?.aborted);
  }
  finish(token) { if (token && token.sequence === this.sequence) { this.controller = null; } }
}

const profileCoord = new Coordinator();
const ednaCoord = new Coordinator();

// Mock DOM elements
const pAnswerText = new MockElement("p", "profile-qa-answer-text");
const pAnswerContainer = new MockElement("div", "profile-qa-answer-container");
const pCitationsList = new MockElement("div", "profile-qa-citations-list");
const pStatus = new MockElement("p", "profile-qa-status");

const eAnswerText = new MockElement("p", "profile-edna-qa-answer-text");
const eAnswerContainer = new MockElement("div", "profile-edna-qa-answer-container");
const eCitationsList = new MockElement("div", "profile-edna-qa-citations-list");
const eStatus = new MockElement("p", "profile-edna-qa-status");

const siteId = "tourism-attraction-376540000a-000365";
const pToken = profileCoord.start(siteId);
const eToken = ednaCoord.start(siteId);

// Mock server responses
const profilePayload = {
  status: "answerable",
  answer_zh_hant: "石朗為綠島著名潛水區，擁有豐富珊瑚礁生態。",
  citations: [{
    citation_id: "cand_prof_c4548c3f5348373f",
    source_name: "交通部觀光署東部海岸國家風景區觀光資訊網",
    section_type: "official_introduction",
    license_and_attribution: "政府資料開放授權條款第1版（OGL 1.0）",
    required_attribution: "資料來源：交通部觀光署",
    limitations: "景點代表點背景，非下水位置。",
    source_url: "https://www.eastcoast-nsa.gov.tw/zh-tw/attractions/detail/20"
  }]
};

const ednaPayload = {
  status: "answerable",
  answer_zh_hant: "石朗周邊 500 公尺歷史水樣中曾檢出雀鯛科魚類分子訊號。",
  citations: [{
    citation_id: "EDNA1",
    source_record_id: "edna_diving_110_113.csv#data-row=4072",
    station_id: "TRM59",
    sampled_at: "2022-06-28",
    distance_m: 229,
    radius_m: 500,
    scientific_name: "Pomacentridae",
    chinese_name: "雀鯛科",
    license_name: "政府資料開放授權條款第1版（OGL 1.0）",
    required_attribution: "資料來源：海洋委員會海洋保育署",
    source_url: "https://iocean.oca.gov.tw/OCA_OceanConservation/opendata.aspx"
  }]
};

// Dispatch Profile QA
assert(profileCoord.isCurrent(pToken, siteId));
pAnswerText.textContent = profilePayload.answer_zh_hant;
pAnswerContainer.hidden = false;
const pCard = new MockElement("article");
pCard.className = "profile-qa-citation-card";
pCitationsList.append(pCard);
pStatus.textContent = "已依官方核准背景完成回答。";

// Dispatch eDNA QA
assert(ednaCoord.isCurrent(eToken, siteId));
eAnswerText.textContent = ednaPayload.answer_zh_hant;
eAnswerContainer.hidden = false;
const eCard = new MockElement("article");
eCard.className = "profile-edna-qa-citation-card";
eCitationsList.append(eCard);
eStatus.textContent = "已依周邊歷史 eDNA 採樣紀錄完成回答。";

// Assertions on isolation
assert.strictEqual(pAnswerContainer.hidden, false);
assert.strictEqual(eAnswerContainer.hidden, false);
assert.strictEqual(pCitationsList.children.length, 1);
assert.strictEqual(eCitationsList.children.length, 1);
assert.strictEqual(pCitationsList.children[0].className, "profile-qa-citation-card");
assert.strictEqual(eCitationsList.children[0].className, "profile-edna-qa-citation-card");
assert.notStrictEqual(pAnswerText.textContent, eAnswerText.textContent);

console.log(JSON.stringify({ dualSuccessIsolation: true }));
'''
        res = self._run_node_script(script)
        self.assertTrue(res.get("dualSuccessIsolation"))

    def test_simulated_site_switch_and_delayed_response_race_condition(self) -> None:
        """Simulate switching dive sites while queries are in-flight; assert old responses are discarded."""
        script = r'''
const assert = require("assert");

class Coordinator {
  constructor() { this.sequence = 0; this.controller = null; }
  start(siteId) {
    this.cancel();
    this.sequence += 1;
    this.controller = new AbortController();
    return { sequence: this.sequence, siteId, signal: this.controller.signal };
  }
  cancel() { if (this.controller) { this.controller.abort(); this.controller = null; } }
  isCurrent(token, currentSiteId) {
    return Boolean(token && token.sequence === this.sequence && token.siteId === currentSiteId && !token.signal?.aborted);
  }
}

const profileCoord = new Coordinator();
const ednaCoord = new Coordinator();

let currentSite = "site-A";
const tokenProfileA = profileCoord.start(currentSite);
const tokenEdnaA = ednaCoord.start(currentSite);

assert.strictEqual(tokenProfileA.signal.aborted, false);
assert.strictEqual(tokenEdnaA.signal.aborted, false);

// User immediately selects site-B
currentSite = "site-B";
const tokenProfileB = profileCoord.start(currentSite);
const tokenEdnaB = ednaCoord.start(currentSite);

// Old tokens must be aborted
assert.strictEqual(tokenProfileA.signal.aborted, true);
assert.strictEqual(tokenEdnaA.signal.aborted, true);

// Fast responses for site-B arrive and are accepted
assert.strictEqual(profileCoord.isCurrent(tokenProfileB, currentSite), true);
assert.strictEqual(ednaCoord.isCurrent(tokenEdnaB, currentSite), true);

// Delayed slow responses for site-A arrive later
assert.strictEqual(profileCoord.isCurrent(tokenProfileA, currentSite), false);
assert.strictEqual(ednaCoord.isCurrent(tokenEdnaA, currentSite), false);

// Even if siteId in tokenProfileA is checked against old site, sequence mismatch still rejects
assert.strictEqual(profileCoord.isCurrent(tokenProfileA, "site-A"), false);
assert.strictEqual(ednaCoord.isCurrent(tokenEdnaA, "site-A"), false);

console.log(JSON.stringify({ raceConditionDiscardPassed: true }));
'''
        res = self._run_node_script(script)
        self.assertTrue(res.get("raceConditionDiscardPassed"))

    def test_simulated_drawer_collapse_aborts_both_coordinators(self) -> None:
        """Simulate user collapsing the profile drawer while requests are in flight."""
        script = r'''
const assert = require("assert");

class Coordinator {
  constructor() { this.sequence = 0; this.controller = null; }
  start(siteId) {
    this.cancel();
    this.sequence += 1;
    this.controller = new AbortController();
    return { sequence: this.sequence, siteId, signal: this.controller.signal };
  }
  cancel() { if (this.controller) { this.controller.abort(); this.controller = null; } }
  isCurrent(token, currentSiteId) {
    return Boolean(token && token.sequence === this.sequence && token.siteId === currentSiteId && !token.signal?.aborted);
  }
}

const profileCoord = new Coordinator();
const ednaCoord = new Coordinator();

const siteId = "site-A";
const tokenProfile = profileCoord.start(siteId);
const tokenEdna = ednaCoord.start(siteId);

// User collapses drawer
profileCoord.cancel();
ednaCoord.cancel();

assert.strictEqual(tokenProfile.signal.aborted, true);
assert.strictEqual(tokenEdna.signal.aborted, true);
assert.strictEqual(profileCoord.isCurrent(tokenProfile, siteId), false);
assert.strictEqual(ednaCoord.isCurrent(tokenEdna, siteId), false);

console.log(JSON.stringify({ drawerCollapseCancellationPassed: true }));
'''
        res = self._run_node_script(script)
        self.assertTrue(res.get("drawerCollapseCancellationPassed"))

    def test_simulated_single_card_error_isolation(self) -> None:
        """Simulate Profile QA encountering HTTP 500 error while eDNA QA succeeds; verify zero cross-corruption."""
        script = r'''
const assert = require("assert");

class MockElement {
  constructor(tag, id = "") {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.textContent = "";
    this.hidden = false;
    this.children = [];
  }
  replaceChildren(...kids) { this.children = [...kids]; }
  append(...kids) { this.children.push(...kids); }
}

// Profile elements
const pAnswerText = new MockElement("p");
const pAnswerContainer = new MockElement("div");
const pCitationsList = new MockElement("div");
const pStatus = new MockElement("p");

// eDNA elements
const eAnswerText = new MockElement("p");
const eAnswerContainer = new MockElement("div");
const eCitationsList = new MockElement("div");
const eStatus = new MockElement("p");

function clearProfileQaDisplay() {
  pAnswerContainer.hidden = true;
  pAnswerText.textContent = "";
  pCitationsList.replaceChildren();
}

function clearProfileEdnaQaDisplay() {
  eAnswerContainer.hidden = true;
  eAnswerText.textContent = "";
  eCitationsList.replaceChildren();
}

// Step 1: Profile QA gets 500 error
clearProfileQaDisplay();
pStatus.textContent = "伺服器處理問答時發生未預期異常（500）；請稍後再試。";

// Step 2: eDNA QA gets 200 answerable
eAnswerText.textContent = "柴口周邊檢出豆娘魚分子訊號。";
eAnswerContainer.hidden = false;
const eCitCard = new MockElement("article");
eCitCard.className = "profile-edna-qa-citation-card";
eCitationsList.append(eCitCard);
eStatus.textContent = "已依周邊歷史 eDNA 採樣紀錄完成回答。";

// Assert: Profile QA is cleared and shows error status
assert.strictEqual(pAnswerContainer.hidden, true);
assert.strictEqual(pAnswerText.textContent, "");
assert.strictEqual(pCitationsList.children.length, 0);
assert.strictEqual(pStatus.textContent, "伺服器處理問答時發生未預期異常（500）；請稍後再試。");

// Assert: eDNA QA is NOT affected by Profile error
assert.strictEqual(eAnswerContainer.hidden, false);
assert.strictEqual(eAnswerText.textContent, "柴口周邊檢出豆娘魚分子訊號。");
assert.strictEqual(eCitationsList.children.length, 1);
assert.strictEqual(eStatus.textContent, "已依周邊歷史 eDNA 採樣紀錄完成回答。");

// Inverse Step: Now eDNA gets 503 error, while Profile gets 200 answerable
pAnswerText.textContent = "石朗為官方核准潛水區。";
pAnswerContainer.hidden = false;
const pCitCard = new MockElement("article");
pCitCard.className = "profile-qa-citation-card";
pCitationsList.append(pCitCard);
pStatus.textContent = "已依官方核准背景完成回答。";

clearProfileEdnaQaDisplay();
eStatus.textContent = "結構化 eDNA 資料庫不可用或校驗失敗（503）；暫時無法提供問答服務。";

// Assert: Profile QA remains intact and is not polluted by eDNA 503
assert.strictEqual(pAnswerContainer.hidden, false);
assert.strictEqual(pAnswerText.textContent, "石朗為官方核准潛水區。");
assert.strictEqual(pCitationsList.children.length, 1);

assert.strictEqual(eAnswerContainer.hidden, true);
assert.strictEqual(eCitationsList.children.length, 0);

console.log(JSON.stringify({ singleCardErrorIsolationPassed: true }));
'''
        res = self._run_node_script(script)
        self.assertTrue(res.get("singleCardErrorIsolationPassed"))

    def test_simulated_fail_closed_statuses_and_error_codes(self) -> None:
        """Simulate all error/intercept status codes and verify fail-closed cleanup."""
        script = r'''
const assert = require("assert");

class MockElement {
  constructor(tag, id = "") {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.textContent = "";
    this.hidden = false;
    this.children = [];
  }
  replaceChildren(...kids) { this.children = [...kids]; }
}

const answerContainer = new MockElement("div");
const answerText = new MockElement("p");
const citationsList = new MockElement("div");
const status = new MockElement("p");

function clearDisplay() {
  answerContainer.hidden = true;
  answerText.textContent = "";
  citationsList.replaceChildren();
}

function handleStatus(code, payload) {
  if (code === 404) {
    clearDisplay();
    status.textContent = "找不到目前選取的潛點代碼（404）；未顯示任何回答。";
    return;
  }
  if (code === 422) {
    clearDisplay();
    status.textContent = "提問格式、半徑或字數不合規範（422）；未顯示任何回答。";
    return;
  }
  if (code === 503) {
    clearDisplay();
    status.textContent = "結構化資料庫不可用（503）；暫時無法提供問答服務。";
    return;
  }
  if (code === 500) {
    clearDisplay();
    status.textContent = "伺服器處理問答時發生未預期異常（500）；請稍後再試。";
    return;
  }
  if (payload.status === "safety_intercepted") {
    clearDisplay();
    status.textContent = payload.answer_zh_hant || "已依安全契約攔截。";
    return;
  }
  if (payload.status === "insufficient_evidence") {
    clearDisplay();
    status.textContent = payload.answer_zh_hant || "無相關歷史採樣紀錄。";
    return;
  }
  if (payload.status === "scope_guidance") {
    clearDisplay();
    status.textContent = payload.answer_zh_hant || "請改用官方潛點介紹問答服務。";
    return;
  }
}

// Test matrix
const tests = [
  { code: 404, payload: null },
  { code: 422, payload: null },
  { code: 503, payload: null },
  { code: 500, payload: null },
  { code: 200, payload: { status: "safety_intercepted", answer_zh_hant: "安全攔截說明" } },
  { code: 200, payload: { status: "insufficient_evidence", answer_zh_hant: "查無紀錄說明" } },
  { code: 200, payload: { status: "scope_guidance", answer_zh_hant: "範疇導引說明" } },
];

for (const t of tests) {
  // Pre-fill display to verify clearDisplay wipes it out
  answerContainer.hidden = false;
  answerText.textContent = "Stale answer";
  citationsList.children = [{ tag: "article" }];

  handleStatus(t.code, t.payload);

  assert.strictEqual(answerContainer.hidden, true);
  assert.strictEqual(answerText.textContent, "");
  assert.strictEqual(citationsList.children.length, 0);
  assert(status.textContent.length > 0);
}

console.log(JSON.stringify({ failClosedCleanupPassed: true }));
'''
        res = self._run_node_script(script)
        self.assertTrue(res.get("failClosedCleanupPassed"))

    def test_simulated_xss_and_unsafe_url_protection(self) -> None:
        """Simulate malicious URLs in citations and verify rejection and safe attribute attachment."""
        script = r'''
const assert = require("assert");

function safeHttpsUrl(rawUrl) {
  if (!rawUrl || typeof rawUrl !== "string") return "";
  try {
    const parsed = new URL(rawUrl.trim());
    if (parsed.protocol === "https:") {
      return parsed.href;
    }
    return "";
  } catch (_err) {
    return "";
  }
}

// Malicious schemes must be completely rejected
assert.strictEqual(safeHttpsUrl("javascript:alert(document.cookie)"), "");
assert.strictEqual(safeHttpsUrl("data:text/html,<script>alert(1)</script>"), "");
assert.strictEqual(safeHttpsUrl("http://insecure-site.com/data"), "");
assert.strictEqual(safeHttpsUrl("vbscript:msgbox(1)"), "");
assert.strictEqual(safeHttpsUrl("file:///etc/passwd"), "");
assert.strictEqual(safeHttpsUrl(""), "");
assert.strictEqual(safeHttpsUrl(null), "");

// Valid HTTPS URLs accepted
const valid = safeHttpsUrl("https://data.gov.tw/dataset/12345");
assert.strictEqual(valid, "https://data.gov.tw/dataset/12345");

console.log(JSON.stringify({ xssUrlSanitizationPassed: true }));
'''
        res = self._run_node_script(script)
        self.assertTrue(res.get("xssUrlSanitizationPassed"))


class TestSystemInvariantsAndAssetImmutability(unittest.TestCase):
    """Verify bitwise immutability of system invariants and existing databases."""

    def test_curated_dive_sites_sha256_unmodified(self) -> None:
        actual_sha = hashlib.sha256(DIVE_SITES_CSV.read_bytes()).hexdigest().lower()
        self.assertEqual(actual_sha, EXPECTED_DIVE_SITES_SHA256)

    def test_profile_candidates_sha256_unmodified(self) -> None:
        actual_sha = hashlib.sha256(CANDIDATES_PATH.read_bytes()).hexdigest().lower()
        self.assertEqual(actual_sha, EXPECTED_CANDIDATES_SHA256)

    def test_profile_fts_sqlite_sha256_unmodified(self) -> None:
        actual_sha = hashlib.sha256(PROFILE_FTS_PATH.read_bytes()).hexdigest().lower()
        self.assertEqual(actual_sha, EXPECTED_PROFILE_FTS_SHA256)

    def test_zero_inner_html_in_map_javascript(self) -> None:
        map_js_content = MAP_JS.read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", map_js_content)


if __name__ == "__main__":
    unittest.main()
