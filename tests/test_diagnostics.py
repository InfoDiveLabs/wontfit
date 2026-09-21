import unittest
from importlib import resources

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

SOURCE = resources.files("wontfit").joinpath("assets", "diagnostics.js").read_text(encoding="utf-8")

LTR_PAGE = """<!doctype html><html><head><meta name="viewport" content="width=device-width">
<style>body{margin:0} .skip{position:absolute;left:-9999px;top:0} .wide{width:520px;height:20px}</style>
</head><body><a class="skip" href="#main">Skip to content</a>
<main id="main"><div class="wide">x</div></main></body></html>"""

LTR_CLIPPED_ONLY = """<!doctype html><html><head><meta name="viewport" content="width=device-width">
<style>body{margin:0} .skip{position:absolute;left:-9999px;top:0}</style>
</head><body><a class="skip" href="#main">Skip to content</a><main id="main">fits</main></body></html>"""

RTL_PAGE = """<!doctype html><html dir="rtl"><head><meta name="viewport" content="width=device-width">
<style>body{margin:0} .skip{position:absolute;right:-9999px;top:0} .wide{width:520px;height:20px}</style>
</head><body><a class="skip" href="#main">Skip</a>
<main id="main"><div class="wide">x</div></main></body></html>"""


def _browser_available():
    if sync_playwright is None:
        return False
    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:
        return False


@unittest.skipUnless(_browser_available(), "needs playwright and chromium (pip install playwright)")
class OverflowCulpritTests(unittest.TestCase):
    def analyze(self, html):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 375, "height": 800})
            page.set_content(html)
            page.evaluate(SOURCE)
            report = page.evaluate("WontfitDiagnostics.analyze(document)")
            browser.close()
        return report["overflow"]

    def test_offscreen_left_skip_link_is_not_a_culprit(self):
        overflow = self.analyze(LTR_PAGE)
        labels = [c["label"] for c in overflow["culprits"]]
        self.assertEqual(labels[0], "div.wide")
        self.assertNotIn("a.skip", labels)

    def test_clipped_left_content_is_not_overflow(self):
        self.assertIsNone(self.analyze(LTR_CLIPPED_ONLY))

    def test_rtl_page_blames_the_element_past_the_left_edge(self):
        overflow = self.analyze(RTL_PAGE)
        labels = [c["label"] for c in overflow["culprits"]]
        self.assertEqual(labels[0], "div.wide")
        self.assertNotIn("a.skip", labels)


if __name__ == "__main__":
    unittest.main()
