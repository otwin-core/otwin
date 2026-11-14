"""Open dist/demo.html from file:// in Chrome with the network off, and report.

The proof that the bundle is truly client-side: a real browser, a ``file://``
URL, the network switched off, and an assertion that every request the page
makes stays on ``file://``. Prints the page's own timings and the results.

Needs the dev extra: ``pip install playwright`` (uses the installed Google
Chrome; downloads no browser). This is a development tool, not a test: it
needs a built bundle and a browser, which CI does not have.

    python apps/home/web/build_bundle.py
    python apps/home/web/verify_offline.py [--firefox]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DIST = Path(__file__).resolve().parent / "dist" / "demo.html"
TIMEOUT_MS = 15 * 60 * 1000


def main() -> int:
    if not DIST.exists():
        sys.exit("no bundle: run build_bundle.py first")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("this tool needs playwright: pip install playwright")
    requests: list[str] = []
    console: list[str] = []
    with sync_playwright() as p:
        if "--firefox" in sys.argv:
            browser = p.firefox.launch()
        else:
            browser = p.chromium.launch(channel="chrome")
        context = browser.new_context()
        context.set_offline(True)  # the network is off for the whole page
        page = context.new_page()
        page.on("request", lambda r: requests.append(r.url))
        page.on("console", lambda m: console.append(f"{m.type}: {m.text}"))
        page.goto(DIST.as_uri())
        page.wait_for_function("window.__OTWIN_RESULT !== undefined", timeout=TIMEOUT_MS)
        out = page.evaluate("window.__OTWIN_RESULT")
        browser.close()
    leaks = [u for u in requests if not u.startswith("file://")]
    print(f"requests: {len(requests)}, off file://: {len(leaks)}")
    for u in leaks:
        print("  LEAK:", u)
    if not out.get("ok"):
        print("page failed:", out.get("error"))
        for line in console[-20:]:
            print("  console", line)
        return 1
    print("timings (ms):", json.dumps(out["timings"], indent=2))
    print(
        "calibration:",
        out["result"]["calibration"]["verdict"],
        "-",
        out["result"]["calibration"]["headline"],
    )
    for s in out["result"]["scenarios"]:
        print("  •", s["sentence"])
    print(out["result"]["versions"])
    return 2 if leaks else 0


if __name__ == "__main__":
    raise SystemExit(main())
