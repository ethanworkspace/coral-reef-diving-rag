"""Checks for the local research-system home-page navigation."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from test_map_page import asgi_get


ROOT = Path(__file__).resolve().parents[1]
HOME_TEMPLATE = ROOT / "src" / "coral_rag" / "templates" / "home.html"
HOME_CSS = ROOT / "src" / "coral_rag" / "static" / "home.css"


class HomepageNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.template = HOME_TEMPLATE.read_text(encoding="utf-8")
        cls.css = HOME_CSS.read_text(encoding="utf-8")

    def test_homepage_has_the_four_local_navigation_cards(self) -> None:
        status, headers, body = asgi_get("/")
        rendered = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("data-feature=\"research-map\"", rendered)
        self.assertIn("data-feature=\"weather-status\"", rendered)
        self.assertIn("data-feature=\"conservation-knowledge\"", rendered)
        self.assertIn("data-feature=\"research-assistant\"", rendered)
        self.assertIn("href='/map'", rendered)
        self.assertIn("href='/knowledge'", rendered)
        self.assertIn("href='/assistant'", rendered)
        self.assertIn("非生成式", rendered)
        self.assertIn("default-src 'self'", headers["content-security-policy"])

    def test_existing_health_and_coordinate_lookup_remain_available(self) -> None:
        status, _, body = asgi_get("/")
        rendered = body.decode("utf-8")
        self.assertEqual(status, 200)
        for marker in (
            'id="status"',
            'id="lat"',
            'id="lon"',
            "fetch('/api/health')",
            "function lookup()",
            "/api/observations?latitude=",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, rendered)

    def test_research_limitations_are_explicit_and_non_generative(self) -> None:
        status, _, body = asgi_get("/")
        rendered = body.decode("utf-8")
        self.assertEqual(status, 200)
        for text in (
            "研究使用限制",
            "不提供下水安全、合法性、活動適合度或現場海況判定。",
            "景點代表點，不是下水入口或活動範圍。",
            "歷史研究證據，不代表當日現場狀態。",
            "本機非商業研究模式",
            "不會儲存聊天紀錄。",
        ):
            with self.subTest(text=text):
                self.assertIn(text, rendered)
        self.assertNotIn("GPT", rendered)
        self.assertNotIn("推薦潛點", rendered)

    def test_homepage_uses_only_local_assets_and_has_responsive_keyboard_styles(self) -> None:
        self.assertIn('href="/static/home.css"', self.template)
        self.assertNotRegex(self.template, re.compile(r"https?://", re.IGNORECASE))
        self.assertNotIn("@import", self.css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", self.css)
        self.assertIn("@media (max-width: 700px)", self.css)
        self.assertIn("grid-template-columns: 1fr", self.css)
        self.assertIn(":focus-visible", self.css)
        self.assertIn("max-width: 100%", self.css)

    def test_home_css_is_served_without_external_resources(self) -> None:
        status, _, body = asgi_get("/static/home.css")
        self.assertEqual(status, 200)
        self.assertEqual(body.decode("utf-8"), self.css)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
