#!/usr/bin/env python3
"""Regenerate docs/images/*.png from the Ledgerly showcase. Maintainers only.

Needs a virtualenv with Playwright (plus Chromium) and Pillow; neither is a
wontfit dependency:

    python3 -m venv .venv-shots && .venv-shots/bin/pip install playwright pillow
    .venv-shots/bin/python -m playwright install chromium
    .venv-shots/bin/python docs/screenshots.py        # or: PY=.venv-shots/bin/python make screenshots

Starts the showcase server and wontfit on spare ports, drives the harness
in a 1400px-wide Chromium, saves each capture as a palette PNG (well under
400 KB), and stops both servers. Run from the repository root.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"
SHOWCASE_PORT = 3941
PROXY_PORT = 8097
VIEWPORT = {"width": 1400, "height": 960}
PAGES = "/,/pricing,/dashboard"
WIDTHS = "se,iphone15,pixel8"
FRAME_H = 560


def wait_port(port: int, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise SystemExit(f"nothing listening on {port}")


def optimise(path: Path) -> int:
    """Palette-quantise in place; returns the final size in bytes."""
    from PIL import Image

    img = Image.open(path).convert("RGB")
    img.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG).save(
        path, optimize=True
    )
    return path.stat().st_size


def harness_url(query: str) -> str:
    return f"http://127.0.0.1:{PROXY_PORT}/__wontfit?{query}"


def wait_frames(page) -> None:
    """Every frame has finished loading and diagnostics have run (no 'loading' pill left)."""
    page.wait_for_function(
        "() => { const p = [...document.querySelectorAll('.frame .pill')];"
        " return p.length > 0 && p.every(x => x.textContent !== 'loading'); }",
        timeout=30000,
    )
    page.wait_for_timeout(400)


def union_box(boxes):
    left = min(b["x"] for b in boxes)
    top = min(b["y"] for b in boxes)
    right = max(b["x"] + b["width"] for b in boxes)
    bottom = max(b["y"] + b["height"] for b in boxes)
    return {"x": left - 8, "y": top - 8, "width": right - left + 16, "height": bottom - top + 16}


def main() -> int:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    trigger_dir = Path(tempfile.mkdtemp(prefix="wontfit-shots-"))
    (trigger_dir / "dist").mkdir()
    trigger = trigger_dir / "dist" / "app.css"  # watched as the relative glob dist/** for a tidy footer
    trigger.write_text("1")
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    showcase = subprocess.Popen(
        [sys.executable, str(ROOT / "examples/showcase/server.py"), "--port", str(SHOWCASE_PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proxy = subprocess.Popen(
        [
            sys.executable, "-m", "wontfit", "--no-config",
            "--upstream", f"http://localhost:{SHOWCASE_PORT}", "--port", str(PROXY_PORT),
            "--pages", PAGES, "--widths", WIDTHS, "--height", str(FRAME_H),
            "--watch-file", "dist/**", "--watch-interval", "1",
        ],
        cwd=str(trigger_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )  # fmt: skip
    sizes: dict[str, int] = {}
    try:
        wait_port(SHOWCASE_PORT)
        wait_port(PROXY_PORT)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
            page = context.new_page()

            def shot(name: str, **kwargs) -> None:
                path = OUT / f"{name}.png"
                page.screenshot(path=str(path), **kwargs)
                sizes[name] = optimise(path)
                print(f"{name}.png  {sizes[name] // 1024} KB")

            # 1. hero: the landing page at three phone widths, overflow already flagged.
            page.goto(harness_url(f"p=/&w=375,393,412&h={FRAME_H}"))
            wait_frames(page)
            shot("hero", clip={"x": 0, "y": 0, "width": 1400, "height": 760})

            # 2. harness: three pages x three widths, full page.
            page.goto(harness_url(f"p={PAGES}&w=375,393,412&h=440"))
            wait_frames(page)
            page.add_style_tag(content=".foot{position:static}")  # sticky footer would float mid-capture
            shot("harness", full_page=True)

            # 3. overflow: the pricing table frame with its culprit list.
            page.goto(harness_url(f"p=/pricing&w=375,393&h={FRAME_H}"))
            wait_frames(page)
            frames = page.locator(".frame")
            frames.nth(0).screenshot(path=str(OUT / "overflow.png"))
            sizes["overflow"] = optimise(OUT / "overflow.png")
            print(f"overflow.png  {sizes['overflow'] // 1024} KB")

            # 4. tap targets: overlay on, dashboard toolbar.
            page.goto(harness_url(f"p=/dashboard&w=375,393&h={FRAME_H}"))
            wait_frames(page)
            page.check("input[name=tap]")
            page.wait_for_timeout(300)
            frames = page.locator(".frame")
            frames.nth(1).screenshot(path=str(OUT / "tap-targets.png"))
            sizes["tap-targets"] = optimise(OUT / "tap-targets.png")
            print(f"tap-targets.png  {sizes['tap-targets'] // 1024} KB")

            # 5. inspect: hover the hero heading in one frame, highlighted in all three.
            page.goto(harness_url(f"p=/&w=375,393,412&h={FRAME_H}"))
            wait_frames(page)
            page.check("input[name=inspect]")
            page.wait_for_timeout(200)
            h1 = page.frame_locator("iframe").first.locator("h1")
            h1.hover()
            page.wait_for_timeout(400)
            boxes = [page.locator(".frame").nth(i).bounding_box() for i in range(3)]
            clip = union_box(boxes)
            # Reach down to the footer: it shows the hovered element's selector.
            foot = page.locator(".foot").bounding_box()
            clip["height"] = foot["y"] + foot["height"] - clip["y"]
            shot("inspect", clip=clip)

            # 6. landscape: the dashboard header covering the KPI cards.
            page.goto(harness_url("p=/dashboard&w=375,393&h=640&o=l"))
            wait_frames(page)
            boxes = [page.locator(".frame").nth(i).bounding_box() for i in range(2)]
            shot("landscape", clip=union_box(boxes))

            # 7. live reload: touch the watched file, wait for the poll, capture the footer.
            page.goto(harness_url(f"p=/&w=375,393&h={FRAME_H}"))
            wait_frames(page)
            trigger.write_text("2")
            os.utime(trigger, None)
            page.wait_for_function(
                "() => /reload/.test(document.getElementById('watchOut').textContent)", timeout=15000
            )
            wait_frames(page)
            foot = page.locator(".foot").bounding_box()
            shot(
                "live-reload",
                clip={"x": 0, "y": foot["y"] - 150, "width": 1400, "height": foot["height"] + 150},
            )

            browser.close()

        # 8. contact sheet: what `wontfit shoot` writes, straight from the subcommand.
        shots_dir = trigger_dir / "shots"
        subprocess.run(
            [
                sys.executable, "-m", "wontfit", "shoot", "--no-config",
                "--upstream", f"http://localhost:{SHOWCASE_PORT}",
                "--pages", "/,/dashboard", "--widths", WIDTHS, "--height", "720", "--out", str(shots_dir),
            ],
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )  # fmt: skip
        (OUT / "contact-sheet.png").write_bytes((shots_dir / "contact-sheet.png").read_bytes())
        sizes["contact-sheet"] = optimise(OUT / "contact-sheet.png")
        print(f"contact-sheet.png  {sizes['contact-sheet'] // 1024} KB")
    finally:
        proxy.terminate()
        showcase.terminate()
        proxy.wait(timeout=5)
        showcase.wait(timeout=5)
    big = [n for n, s in sizes.items() if s > 400 * 1024]
    if big:
        print(f"WARNING: over 400 KB: {', '.join(big)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
