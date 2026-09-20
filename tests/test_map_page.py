"""Route, safety, accessibility, and fallback checks for the dive-site map MVP."""

from __future__ import annotations

import asyncio
import csv
import json
import tempfile
import unittest
from pathlib import Path

from coral_rag import web


ROOT = Path(__file__).resolve().parents[1]
MAP_HTML = ROOT / "src" / "coral_rag" / "templates" / "map.html"
MAP_JS = ROOT / "src" / "coral_rag" / "static" / "map.js"
EDNA_QUERY_JS = ROOT / "src" / "coral_rag" / "static" / "edna-query.js"
WEATHER_QUERY_JS = ROOT / "src" / "coral_rag" / "static" / "general-weather-query.js"
MAP_CSS = ROOT / "src" / "coral_rag" / "static" / "map.css"
CURATED = ROOT / "data" / "curated" / "dive_sites.csv"
REPRESENTATIVE_POINT_NOTICE = "此座標為景點代表點，不代表下水入口、活動範圍、合法性或安全條件。"


def asgi_get(path: str) -> tuple[int, dict[str, str], bytes]:
    """Exercise FastAPI and mounted static assets without an optional HTTP client."""
    messages: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(web.app(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in start.get("headers", [])
    }
    body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return start["status"], headers, body


class DiveSiteMapPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = MAP_HTML.read_text(encoding="utf-8")
        cls.javascript = MAP_JS.read_text(encoding="utf-8")
        cls.css = MAP_CSS.read_text(encoding="utf-8")

    def test_map_route_assets_version_attribution_and_security_headers(self) -> None:
        status, headers, body = asgi_get("/map")
        rendered = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("潛點地圖", rendered)
        self.assertIn("leaflet@1.9.4", rendered)
        self.assertIn("sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=", rendered)
        self.assertIn("sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=", rendered)
        self.assertIn("© OpenStreetMap contributors", rendered)
        self.assertIn("default-src 'self'", headers["content-security-policy"])
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertEqual(headers["referrer-policy"], "strict-origin-when-cross-origin")

        css_status, _, css_body = asgi_get("/static/map.css")
        js_status, _, js_body = asgi_get("/static/map.js")
        edna_js_status, _, edna_js_body = asgi_get("/static/edna-query.js")
        reefcheck_js_status, _, reefcheck_js_body = asgi_get("/static/reefcheck-query.js")
        weather_js_status, _, weather_js_body = asgi_get("/static/general-weather-query.js")
        self.assertEqual((css_status, js_status, edna_js_status, reefcheck_js_status, weather_js_status), (200, 200, 200, 200, 200))
        self.assertTrue(css_body)
        self.assertTrue(js_body)
        self.assertTrue(edna_js_body)
        self.assertTrue(reefcheck_js_body)
        self.assertTrue(weather_js_body)

    def test_page_loads_api_data_without_hardcoded_curated_sites(self) -> None:
        self.assertIn('const DIVE_SITES_ENDPOINT = "/api/dive-sites"', self.javascript)
        self.assertIn("fetch(DIVE_SITES_ENDPOINT", self.javascript)
        self.assertNotIn("/api/observations", self.html + self.javascript)

        with CURATED.open(encoding="utf-8-sig", newline="") as stream:
            curated = list(csv.DictReader(stream))
        self.assertGreater(len(curated), 0)
        for row in curated:
            self.assertNotIn(row["site_id"], self.html + self.javascript)
            self.assertNotIn(row["name"], self.html + self.javascript)

    def test_empty_error_503_and_map_failure_have_explicit_text_fallbacks(self) -> None:
        required_messages = (
            "正在載入潛點資料",
            "目前沒有已驗證潛點可顯示",
            "資料庫版本尚未就緒（503）",
            "潛點 API 連線失敗",
            "無法連線到潛點 API",
            "互動地圖函式庫載入失敗",
            "底圖圖磚無法載入",
            "潛點清單與基本資訊仍可使用",
        )
        combined = self.html + self.javascript
        for message in required_messages:
            with self.subTest(message=message):
                self.assertIn(message, combined)
        self.assertIn("if (response.status === 503)", self.javascript)
        self.assertIn("Array.isArray(payload.items)", self.javascript)
        self.assertIn("site-list", self.html)

        with tempfile.TemporaryDirectory() as temporary:
            previous_root = web.ROOT
            web.ROOT = Path(temporary)
            try:
                status, _, body = asgi_get("/api/dive-sites")
            finally:
                web.ROOT = previous_root
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"items": [], "count": 0})

    def test_information_panel_accessibility_and_untrusted_text_handling(self) -> None:
        for label in ("代表點座標", "資料品質", "最後核對日期", "官方來源"):
            self.assertIn(label, self.html)
        self.assertIn(REPRESENTATIVE_POINT_NOTICE, self.html)
        self.assertIn(REPRESENTATIVE_POINT_NOTICE, self.javascript)
        self.assertIn('target="_blank" rel="noopener noreferrer"', self.html)
        self.assertIn("url.protocol === \"https:\"", self.javascript)
        self.assertNotIn("innerHTML", self.javascript)
        self.assertIn("textContent", self.javascript)
        self.assertIn('role="status"', self.html)
        self.assertIn('aria-live="polite"', self.html)
        self.assertIn("@media (max-width: 760px)", self.css)
        self.assertIn('button.type = "button"', self.javascript)
        self.assertIn('button.addEventListener("click"', self.javascript)
        self.assertIn("keyboard: true", self.javascript)
        self.assertIn('button.setAttribute("aria-current"', self.javascript)
        self.assertIn('button.scrollIntoView({ block: "nearest" })', self.javascript)
        self.assertIn("map.setView(coordinates", self.javascript)

    def test_homepage_entry_and_existing_functions_remain_available(self) -> None:
        status, _, body = asgi_get("/")
        homepage = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("href='/map'", homepage)
        self.assertIn("fetch('/api/health')", homepage)
        self.assertIn("/api/observations?latitude=", homepage)
        self.assertIn("function lookup()", homepage)
        paths = {route.path for route in web.app.routes}
        self.assertTrue(
            {"/", "/map", "/api/health", "/api/observations", "/api/query",
             "/api/dive-sites", "/api/dive-sites/{site_id}"}.issubset(paths)
        )


if __name__ == "__main__":
    unittest.main()
