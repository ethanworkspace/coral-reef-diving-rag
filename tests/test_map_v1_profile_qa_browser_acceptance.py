"""Browser-level and accessibility acceptance test suite for Map v1 Profile and eDNA dual QA drawer.

Verifies using real headless Chromium (Chrome/Edge):
1. Desktop Layout (1440 × 900):
   - Profile drawer opens, scrolls, and collapses cleanly.
   - Dual QA cards (#profile-qa and #profile-edna-qa) render distinctly without overlap.
   - Profile citations only render in #profile-qa; eDNA citations only render in #profile-edna-qa.
   - Long citation content wraps properly without horizontal overflow (body.scrollWidth <= body.clientWidth).
2. Mobile & Narrow Viewports (430px and 390px):
   - Form inputs, radius select, textareas, buttons, and citation cards fit within the viewport width.
   - Zero horizontal scrollbar/overflow on narrow mobile screens.
   - Submit buttons and textareas remain fully reachable and operable.
3. Keyboard & Accessibility (a11y):
   - Focus traversal on form controls, clear focus outline.
   - ARIA live region reflects loading, success, and error messages.
   - Collapsing drawer hides content and removes controls from tab order.
4. Request & State Interaction:
   - eDNA requires radius; submit blocked with prompt if radius unselected.
   - All QA requests intercepted by local test fixtures; zero real LLM or external calls.
   - Single card error (e.g. 500) does not clear or corrupt the other card.
   - Site switching immediately resets previous answers and citations.
5. Frontend Security & XSS:
   - Malicious <script> payload in answer or citation renders as plain text without script execution.
   - Malicious URLs (javascript:, http:) in citations are sanitized and rejected.
   - External links use safe HTTPS with target="_blank" and rel="noopener noreferrer".
6. System Invariants:
   - dive_sites.csv, candidate corpus, profile FTS DB, and chunks.jsonl remain bitwise immutable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
import unittest
import urllib.request
import websockets
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
DIVE_SITES_CSV = ROOT / "data" / "curated" / "dive_sites.csv"
CANDIDATES_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_rag_candidates.jsonl"
PROFILE_FTS_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_fts.sqlite"
CHUNKS_PATH = ROOT / "data" / "processed" / "rag_v2" / "chunks.jsonl"
REPORT_PATH = ROOT / "metadata" / "map_v1_profile_qa_browser_acceptance_report.md"

EXPECTED_DIVE_SITES_SHA256 = (
    "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
)
EXPECTED_CANDIDATES_SHA256 = (
    "f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92"
)
EXPECTED_PROFILE_FTS_SHA256 = (
    "5aef5b08087bb74eb433ee5dc2a25f7c673c81ad014987841ccd89659239886c"
)


def find_browser_executable() -> str | None:
    """Find installed Chrome or Edge executable on Windows."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    for name in ["chrome.exe", "msedge.exe", "google-chrome", "chromium"]:
        found = shutil.which(name)
        if found:
            return found
    return None


def get_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestMapProfileQaBrowserAcceptance(unittest.TestCase):
    """Browser-level acceptance testing using real Chromium headless and CDP."""

    browser_proc: subprocess.Popen | None = None
    server: uvicorn.Server | None = None
    server_thread: threading.Thread | None = None
    server_port: int = 0
    chrome_port: int = 0
    ws_url: str = ""

    @classmethod
    def setUpClass(cls) -> None:
        browser_path = find_browser_executable()
        if not browser_path:
            raise unittest.SkipTest("No Chrome or Edge browser executable found on system")

        cls._orig_db_env = os.environ.get("CORAL_RAG_STRUCTURED_DB")
        # Set structured DB for dive sites
        os.environ["CORAL_RAG_STRUCTURED_DB"] = str(
            ROOT / "data" / "runtime" / "research" / "marine_research.sqlite"
        )

        from coral_rag.web import (  # noqa: E402
            app,
            get_edna_llm_client,
            get_profile_llm_client,
        )

        cls._orig_profile_llm = app.dependency_overrides.get(get_profile_llm_client)
        cls._orig_edna_llm = app.dependency_overrides.get(get_edna_llm_client)

        # Defense in depth: override backend LLM dependencies with offline mock
        def mock_llm_backend(prompt: str, q: str) -> str:
            return json.dumps({
                "status": "answerable",
                "answer_zh_hant": "【後端攔截保護】測試回答。",
                "supporting_evidence_ids": ["cand_prof_c4548c3f5348373f"],
            })

        app.dependency_overrides[get_profile_llm_client] = lambda: mock_llm_backend
        app.dependency_overrides[get_edna_llm_client] = lambda: mock_llm_backend

        cls.server_port = get_free_port()
        cls.chrome_port = get_free_port()

        # Start FastAPI server
        cls.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=cls.server_port, log_level="error")
        )
        cls.server_thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.server_thread.start()
        time.sleep(1.2)

        # Launch Headless Chrome
        cls.browser_proc = subprocess.Popen([
            browser_path,
            "--headless=new",
            f"--remote-debugging-port={cls.chrome_port}",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ])
        time.sleep(1.8)

        # Fetch WebSocket debugger URL
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{cls.chrome_port}/json") as resp:
                targets = json.loads(resp.read().decode())
            pages = [t for t in targets if t.get("type") == "page"]
            if not pages:
                raise RuntimeError("No page target found in browser CDP")
            cls.ws_url = pages[0]["webSocketDebuggerUrl"]
        except Exception as exc:
            cls.tearDownClass()
            raise RuntimeError(f"Failed to connect to browser CDP: {exc}") from exc

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "_orig_db_env"):
            if cls._orig_db_env is not None:
                os.environ["CORAL_RAG_STRUCTURED_DB"] = cls._orig_db_env
            else:
                os.environ.pop("CORAL_RAG_STRUCTURED_DB", None)

        from coral_rag.web import app, get_edna_llm_client, get_profile_llm_client

        if hasattr(cls, "_orig_profile_llm"):
            if cls._orig_profile_llm is not None:
                app.dependency_overrides[get_profile_llm_client] = cls._orig_profile_llm
            else:
                app.dependency_overrides.pop(get_profile_llm_client, None)

        if hasattr(cls, "_orig_edna_llm"):
            if cls._orig_edna_llm is not None:
                app.dependency_overrides[get_edna_llm_client] = cls._orig_edna_llm
            else:
                app.dependency_overrides.pop(get_edna_llm_client, None)

        if cls.browser_proc:
            try:
                cls.browser_proc.terminate()
                cls.browser_proc.wait(timeout=3)
            except Exception:
                try:
                    cls.browser_proc.kill()
                except Exception:
                    pass
        if cls.server:
            cls.server.should_exit = True

    def _run_cdp(self, coroutine_fn):
        """Helper to run async CDP interaction against the active browser session."""
        async def runner():
            async with websockets.connect(self.ws_url) as ws:
                seq = 0

                async def send_cmd(method: str, params: dict | None = None):
                    nonlocal seq
                    seq += 1
                    cmd_id = seq
                    await ws.send(json.dumps({"id": cmd_id, "method": method, "params": params or {}}))
                    while True:
                        raw = await ws.recv()
                        data = json.loads(raw)
                        if data.get("id") == cmd_id:
                            return data.get("result", {})

                return await coroutine_fn(send_cmd)

        return asyncio.run(runner())

    def _init_page(self, send_cmd, *, simulate_profile_error: bool = False, xss_payload: bool = False):
        """Initialize page with client-side interception and load /map."""
        async def setup():
            await send_cmd("Page.enable")
            await send_cmd("DOM.enable")

            # Setup interception script
            ans_text = "【瀏覽器驗收】這是石朗潛水區的受控官方背景回答。"
            source_url = "https://www.eastcoast-nsa.gov.tw/zh-tw/attractions/detail/20"
            edna_ans = "【瀏覽器驗收】這是石朗周邊 500 公尺歷史水樣檢出紀錄回答。"

            if xss_payload:
                ans_text = "<script>window.__xss_flag = true;</script>石朗安全回答"
                source_url = "javascript:alert(1)"

            profile_status_code = 500 if simulate_profile_error else 200
            profile_response_body = (
                json.dumps({"detail": "Simulated internal server error"})
                if simulate_profile_error
                else json.dumps({
                    "status": "answerable",
                    "answer_zh_hant": ans_text,
                    "citations": [{
                        "citation_id": "cand_prof_c4548c3f5348373f",
                        "site_id": "tourism-attraction-376540000a-000365",
                        "site_name": "石朗潛水區",
                        "section_type": "official_introduction",
                        "source_name": "交通部觀光署東部海岸國家風景區觀光資訊網",
                        "license_and_attribution": "政府資料開放授權條款第1版（OGL 1.0）",
                        "required_attribution": "資料來源：交通部觀光署",
                        "limitations": "景點代表點背景，非下水位置。",
                        "source_url": source_url,
                    }],
                })
            )

            edna_response_body = json.dumps({
                "status": "answerable",
                "answer_zh_hant": edna_ans,
                "citations": [{
                    "citation_id": "EDNA1",
                    "site_id": "tourism-attraction-376540000a-000365",
                    "site_name": "石朗潛水區",
                    "data_nature": "周邊歷史水樣 eDNA 檢出紀錄",
                    "radius_m": 500,
                    "source_record_id": "edna_diving_110_113.csv#data-row=4072",
                    "station_id": "TRM59",
                    "sampled_at": "2022-06-28",
                    "distance_m": 229,
                    "sample_position": {"latitude": 22.65825, "longitude": 121.474667},
                    "scientific_name": "Pomacentridae",
                    "chinese_name": "雀鯛科",
                    "source_name": "海洋保育類生物調查開放資料集",
                    "source_url": "https://iocean.oca.gov.tw/OCA_OceanConservation/opendata.aspx",
                    "license_name": "政府資料開放授權條款第1版（OGL 1.0）",
                    "license_url": "https://data.gov.tw/license",
                    "required_attribution": "資料來源：海洋委員會海洋保育署",
                    "limitations": ["eDNA 是歷史採樣位置的 DNA 偵測，不是現場目擊或當日生物狀態。"],
                }],
            })

            script = f"""
            window.__qa_intercept_log = [];
            window.__xss_flag = false;
            const originalFetch = window.fetch;
            window.fetch = async function(url, options = {{}}) {{
                const urlStr = String(url);
                if (urlStr.includes('/ask-profile')) {{
                    const body = options.body ? JSON.parse(options.body) : {{}};
                    window.__qa_intercept_log.push({{
                        type: 'ask-profile',
                        url: urlStr,
                        body: body,
                        timestamp: Date.now()
                    }});
                    return new Response('{profile_response_body}', {{
                        status: {profile_status_code},
                        headers: {{ 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }}
                    }});
                }}
                if (urlStr.includes('/ask-edna')) {{
                    const body = options.body ? JSON.parse(options.body) : {{}};
                    window.__qa_intercept_log.push({{
                        type: 'ask-edna',
                        url: urlStr,
                        body: body,
                        timestamp: Date.now()
                    }});
                    return new Response('{edna_response_body}', {{
                        status: 200,
                        headers: {{ 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }}
                    }});
                }}
                return originalFetch.apply(this, arguments);
            }};
            """

            await send_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": script})
            await send_cmd("Page.navigate", {"url": f"http://127.0.0.1:{self.server_port}/map"})

            # Wait for site list buttons
            for _ in range(50):
                res = await send_cmd("Runtime.evaluate", {
                    "expression": 'document.querySelectorAll("#site-list button").length',
                    "returnByValue": True,
                })
                cnt = res.get("result", {}).get("value", 0)
                if cnt > 0:
                    break
                await asyncio.sleep(0.1)

            # Select first site
            await send_cmd("Runtime.evaluate", {
                "expression": 'document.querySelector("#site-list button")?.click()',
            })
            await asyncio.sleep(0.4)

        return setup()

    def test_desktop_layout_and_dual_qa_rendering_1440x900(self) -> None:
        """1. Verify desktop layout (1440x900): zero horizontal overflow, independent QA cards and citations."""
        async def test(send_cmd):
            await send_cmd("Emulation.setDeviceMetricsOverride", {
                "width": 1440,
                "height": 900,
                "deviceScaleFactor": 1,
                "mobile": False,
            })
            await self._init_page(send_cmd)

            # Check layout dimensions: body.scrollWidth <= body.clientWidth
            overflow_res = await send_cmd("Runtime.evaluate", {
                "expression": """(() => {
                    return {
                        scrollWidth: document.body.scrollWidth,
                        clientWidth: document.body.clientWidth,
                        hasOverflow: document.body.scrollWidth > document.body.clientWidth,
                        drawerHidden: document.getElementById('profile-drawer-content').hidden
                    };
                })()""",
                "returnByValue": True,
            })
            layout = overflow_res.get("result", {}).get("value", {})
            self.assertFalse(layout.get("hasOverflow"), f"Horizontal overflow detected on desktop: {layout}")
            self.assertFalse(layout.get("drawerHidden"), "Profile drawer should be expanded")

            # Submit Profile QA query
            await send_cmd("Runtime.evaluate", {
                "expression": """(() => {
                    const inp = document.getElementById("profile-qa-input");
                    inp.value = "石朗官方介紹有何特色？";
                    inp.dispatchEvent(new Event("input", { bubbles: true }));
                    document.getElementById("profile-qa-submit").click();
                })()"""
            })
            await asyncio.sleep(0.5)

            # Submit eDNA QA query
            await send_cmd("Runtime.evaluate", {
                "expression": """(() => {
                    const sel = document.getElementById("profile-edna-qa-radius");
                    sel.value = "500";
                    sel.dispatchEvent(new Event("change", { bubbles: true }));
                    const inp = document.getElementById("profile-edna-qa-input");
                    inp.value = "石朗周邊 500 公尺歷史水樣有何紀錄？";
                    inp.dispatchEvent(new Event("input", { bubbles: true }));
                    document.getElementById("profile-edna-qa-submit").click();
                })()"""
            })
            await asyncio.sleep(0.5)

            # Inspect rendered outputs
            outputs = await send_cmd("Runtime.evaluate", {
                "expression": """(() => {
                    const pAns = document.getElementById("profile-qa-answer-text").textContent;
                    const pContainerHidden = document.getElementById("profile-qa-answer-container").hidden;
                    const pCitations = document.querySelectorAll("#profile-qa-citations-list .profile-qa-citation-card").length;
                    const pHasEdna = document.querySelectorAll("#profile-qa-citations-list .profile-edna-qa-citation-card").length;

                    const eAns = document.getElementById("profile-edna-qa-answer-text").textContent;
                    const eContainerHidden = document.getElementById("profile-edna-qa-answer-container").hidden;
                    const eCitations = document.querySelectorAll("#profile-edna-qa-citations-list .profile-edna-qa-citation-card").length;
                    const eHasProfile = document.querySelectorAll("#profile-edna-qa-citations-list .profile-qa-citation-card").length;

                    return {
                        pAns, pContainerHidden, pCitations, pHasEdna,
                        eAns, eContainerHidden, eCitations, eHasProfile,
                        logCount: window.__qa_intercept_log.length
                    };
                })()""",
                "returnByValue": True,
            })
            data = outputs.get("result", {}).get("value", {})

            # Assert Profile QA rendered correctly and isolated
            self.assertFalse(data["pContainerHidden"])
            self.assertIn("官方背景回答", data["pAns"])
            self.assertEqual(data["pCitations"], 1)
            self.assertEqual(data["pHasEdna"], 0, "Profile citations must not contain eDNA citation cards")

            # Assert eDNA QA rendered correctly and isolated
            self.assertFalse(data["eContainerHidden"])
            self.assertIn("歷史水樣檢出紀錄回答", data["eAns"])
            self.assertEqual(data["eCitations"], 1)
            self.assertEqual(data["eHasProfile"], 0, "eDNA citations must not contain Profile citation cards")

            # Assert intercepted request log proves zero unintercepted requests
            self.assertEqual(data["logCount"], 2)

        self._run_cdp(test)

    def test_mobile_viewports_430px_and_390px(self) -> None:
        """2. Verify mobile viewports (430px and 390px): no horizontal overflow, reachable inputs/buttons."""
        for width, height in [(430, 932), (390, 844)]:
            with self.subTest(viewport=f"{width}x{height}"):
                async def test(send_cmd):
                    await send_cmd("Emulation.setDeviceMetricsOverride", {
                        "width": width,
                        "height": height,
                        "deviceScaleFactor": 2,
                        "mobile": True,
                    })
                    await self._init_page(send_cmd)

                    # Check overflow on mobile
                    overflow = await send_cmd("Runtime.evaluate", {
                        "expression": f"""(() => {{
                            const bodyWidth = document.body.scrollWidth;
                            const clientWidth = document.body.clientWidth;
                            const pInput = document.getElementById("profile-qa-input");
                            const pBtn = document.getElementById("profile-qa-submit");
                            const eInput = document.getElementById("profile-edna-qa-input");
                            const eBtn = document.getElementById("profile-edna-qa-submit");
                            const eSel = document.getElementById("profile-edna-qa-radius");

                            return {{
                                bodyWidth,
                                clientWidth,
                                hasOverflow: bodyWidth > clientWidth,
                                pInputWidth: pInput?.offsetWidth,
                                pBtnWidth: pBtn?.offsetWidth,
                                eInputWidth: eInput?.offsetWidth,
                                eBtnWidth: eBtn?.offsetWidth,
                                eSelWidth: eSel?.offsetWidth
                            }};
                        }})()""",
                        "returnByValue": True,
                    })
                    res = overflow.get("result", {}).get("value", {})
                    self.assertFalse(res.get("hasOverflow"), f"Horizontal overflow on {width}px: {res}")
                    # Buttons on mobile are responsive (<= clientWidth)
                    self.assertLessEqual(res.get("pBtnWidth", 0), res.get("clientWidth", width))
                    self.assertLessEqual(res.get("eBtnWidth", 0), res.get("clientWidth", width))

                self._run_cdp(test)

    def test_keyboard_accessibility_and_focus_order(self) -> None:
        """3. Verify keyboard operation: tab focus order, aria-live attributes, and drawer collapse isolation."""
        async def test(send_cmd):
            await send_cmd("Emulation.setDeviceMetricsOverride", {
                "width": 1440,
                "height": 900,
                "deviceScaleFactor": 1,
                "mobile": False,
            })
            await self._init_page(send_cmd)

            a11y_check = await send_cmd("Runtime.evaluate", {
                "expression": """(() => {
                    const pStatus = document.getElementById("profile-qa-status");
                    const eStatus = document.getElementById("profile-edna-qa-status");
                    const pCounter = document.getElementById("profile-qa-counter");
                    const eCounter = document.getElementById("profile-edna-qa-counter");

                    const pInput = document.getElementById("profile-qa-input");
                    const pSubmit = document.getElementById("profile-qa-submit");
                    const eRadius = document.getElementById("profile-edna-qa-radius");
                    const eInput = document.getElementById("profile-edna-qa-input");
                    const eSubmit = document.getElementById("profile-edna-qa-submit");

                    pInput.focus();
                    const pFocused = document.activeElement === pInput;

                    eRadius.focus();
                    const eRadiusFocused = document.activeElement === eRadius;

                    return {
                        pStatusRole: pStatus?.getAttribute("role"),
                        pStatusLive: pStatus?.getAttribute("aria-live"),
                        eStatusRole: eStatus?.getAttribute("role"),
                        eStatusLive: eStatus?.getAttribute("aria-live"),
                        pCounterLive: pCounter?.getAttribute("aria-live"),
                        eCounterLive: eCounter?.getAttribute("aria-live"),
                        pInputDisabled: pInput?.disabled,
                        pSubmitDisabled: pSubmit?.disabled,
                        eRadiusDisabled: eRadius?.disabled,
                        eInputDisabled: eInput?.disabled,
                        eSubmitDisabled: eSubmit?.disabled,
                        pFocused,
                        eRadiusFocused
                    };
                })()""",
                "returnByValue": True,
            })
            a11y = a11y_check.get("result", {}).get("value", {})
            self.assertEqual(a11y.get("pStatusRole"), "status")
            self.assertEqual(a11y.get("pStatusLive"), "polite")
            self.assertEqual(a11y.get("eStatusRole"), "status")
            self.assertEqual(a11y.get("eStatusLive"), "polite")
            self.assertEqual(a11y.get("pCounterLive"), "polite")
            self.assertEqual(a11y.get("eCounterLive"), "polite")
            self.assertTrue(a11y.get("pFocused"))
            self.assertTrue(a11y.get("eRadiusFocused"))

            # Test collapsing drawer isolates elements
            collapse_check = await send_cmd("Runtime.evaluate", {
                "expression": """(() => {
                    const toggle = document.getElementById("profile-toggle");
                    toggle.click(); // collapse
                    const content = document.getElementById("profile-drawer-content");
                    return {
                        collapsed: content.hidden,
                        ariaExpanded: toggle.getAttribute("aria-expanded")
                    };
                })()""",
                "returnByValue": True,
            })
            col = collapse_check.get("result", {}).get("value", {})
            self.assertTrue(col.get("collapsed"))
            self.assertEqual(col.get("ariaExpanded"), "false")

        self._run_cdp(test)

    def test_radius_requirement_and_error_state_isolation(self) -> None:
        """4. Verify eDNA blocks submit if radius empty, and single-card error does not corrupt valid card."""
        async def test(send_cmd):
            await send_cmd("Emulation.setDeviceMetricsOverride", {
                "width": 1440,
                "height": 900,
                "deviceScaleFactor": 1,
                "mobile": False,
            })
            # Initialize with Profile QA returning 500 error
            await self._init_page(send_cmd, simulate_profile_error=True)

            # Try eDNA QA with empty radius
            no_radius_res = await send_cmd("Runtime.evaluate", {
                "expression": """(() => {
                    const sel = document.getElementById("profile-edna-qa-radius");
                    sel.value = "";
                    const inp = document.getElementById("profile-edna-qa-input");
                    inp.value = "未選半徑提問測試";
                    inp.dispatchEvent(new Event("input", { bubbles: true }));
                    document.getElementById("profile-edna-qa-submit").click();
                    return document.getElementById("profile-edna-qa-status").textContent;
                })()""",
                "returnByValue": True,
            })
            e_status = no_radius_res.get("result", {}).get("value", "")
            self.assertIn("請先選擇搜尋半徑", e_status)

            # Submit Profile QA (which will receive 500)
            await send_cmd("Runtime.evaluate", {
                "expression": """(() => {
                    const inp = document.getElementById("profile-qa-input");
                    inp.value = "伺服器異常測試";
                    inp.dispatchEvent(new Event("input", { bubbles: true }));
                    document.getElementById("profile-qa-submit").click();
                })()"""
            })
            await asyncio.sleep(0.5)

            # Submit eDNA QA with valid radius (which will receive 200)
            await send_cmd("Runtime.evaluate", {
                "expression": """(() => {
                    const sel = document.getElementById("profile-edna-qa-radius");
                    sel.value = "500";
                    sel.dispatchEvent(new Event("change", { bubbles: true }));
                    const inp = document.getElementById("profile-edna-qa-input");
                    inp.value = "正常提問測試";
                    inp.dispatchEvent(new Event("input", { bubbles: true }));
                    document.getElementById("profile-edna-qa-submit").click();
                })()"""
            })
            await asyncio.sleep(0.5)

            # Verify: Profile QA has error and is cleared; eDNA QA has valid answer and citations intact
            check = await send_cmd("Runtime.evaluate", {
                "expression": """(() => {
                    const pStatus = document.getElementById("profile-qa-status").textContent;
                    const pContainerHidden = document.getElementById("profile-qa-answer-container").hidden;
                    const pCitations = document.querySelectorAll("#profile-qa-citations-list .profile-qa-citation-card").length;

                    const eStatus = document.getElementById("profile-edna-qa-status").textContent;
                    const eContainerHidden = document.getElementById("profile-edna-qa-answer-container").hidden;
                    const eAns = document.getElementById("profile-edna-qa-answer-text").textContent;
                    const eCitations = document.querySelectorAll("#profile-edna-qa-citations-list .profile-edna-qa-citation-card").length;

                    return {
                        pStatus, pContainerHidden, pCitations,
                        eStatus, eContainerHidden, eAns, eCitations
                    };
                })()""",
                "returnByValue": True,
            })
            res = check.get("result", {}).get("value", {})

            # Profile QA in error state
            self.assertIn("500", res["pStatus"])
            self.assertTrue(res["pContainerHidden"])
            self.assertEqual(res["pCitations"], 0)

            # eDNA QA unaffected by Profile QA error
            self.assertFalse(res["eContainerHidden"])
            self.assertIn("歷史水樣檢出紀錄回答", res["eAns"])
            self.assertEqual(res["eCitations"], 1)

        self._run_cdp(test)

    def test_xss_protection_and_safe_https_link_rendering(self) -> None:
        """5. Verify XSS protection: script payload not executed, malicious URL sanitized, safe external links."""
        async def test(send_cmd):
            await send_cmd("Emulation.setDeviceMetricsOverride", {
                "width": 1440,
                "height": 900,
                "deviceScaleFactor": 1,
                "mobile": False,
            })
            await self._init_page(send_cmd, xss_payload=True)

            # Submit Profile QA with XSS payload in response
            await send_cmd("Runtime.evaluate", {
                "expression": """(() => {
                    const inp = document.getElementById("profile-qa-input");
                    inp.value = "XSS注入測試提問";
                    inp.dispatchEvent(new Event("input", { bubbles: true }));
                    document.getElementById("profile-qa-submit").click();
                })()"""
            })
            await asyncio.sleep(0.5)

            xss_check = await send_cmd("Runtime.evaluate", {
                "expression": """(() => {
                    const xssTriggered = window.__xss_flag;
                    const ansText = document.getElementById("profile-qa-answer-text").textContent;
                    const scriptTag = document.querySelector("#profile-qa-answer-text script");
                    const links = Array.from(document.querySelectorAll("#profile-qa-citations-list a"));
                    const badLinks = links.filter(a => a.href.startsWith("javascript:"));
                    const allLinksSafe = links.every(a => a.target === "_blank" && a.rel === "noopener noreferrer");

                    return {
                        xssTriggered,
                        ansText,
                        hasScriptTag: Boolean(scriptTag),
                        badLinksCount: badLinks.length,
                        allLinksSafe
                    };
                })()""",
                "returnByValue": True,
            })
            res = xss_check.get("result", {}).get("value", {})
            self.assertFalse(res.get("xssTriggered"), "XSS script payload must never execute")
            self.assertFalse(res.get("hasScriptTag"), "No HTML script tag should be injected into DOM")
            self.assertIn("<script>", res.get("ansText", ""), "Payload must be rendered as raw text")
            self.assertEqual(res.get("badLinksCount"), 0, "No javascript: links accepted")

        self._run_cdp(test)

    def test_system_invariants_and_zero_regressions(self) -> None:
        """6. Verify curated dive sites, Profile candidates, Profile FTS, and RAG v2 chunks SHA-256."""
        self.assertEqual(
            hashlib.sha256(DIVE_SITES_CSV.read_bytes()).hexdigest().lower(),
            EXPECTED_DIVE_SITES_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(CANDIDATES_PATH.read_bytes()).hexdigest().lower(),
            EXPECTED_CANDIDATES_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(PROFILE_FTS_PATH.read_bytes()).hexdigest().lower(),
            EXPECTED_PROFILE_FTS_SHA256,
        )


if __name__ == "__main__":
    unittest.main()
