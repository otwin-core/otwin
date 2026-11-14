"""Drive the wizard end to end in a real browser, as a householder would.

Serves ``dist/`` from a local static server (as GitHub Pages would), opens it
in Chrome and goes through the three steps with the sample files:

1. answers the questions with the sample home's answers (``samples/home.json``);
2. drops the electricity CSV and the weather-station CSV on the page, checks
   the column mapper guessed the station's columns, and confirms them;
3. clicks "Calibrate my home" and waits for the report.

It asserts every request stays on the local server (nothing uploaded,
nothing fetched from elsewhere) and prints the report and the timings.

    python apps/home/web/build_bundle.py
    python apps/home/web/verify_wizard.py [--formats] [--file] [--screenshot PATH]

``--formats`` also drops every ingest test fixture and prints how each was
read. ``--file`` runs from ``file://`` instead of the server (the engine
then runs on the page, as workers are forbidden there). Needs
``pip install playwright``; uses the installed Google Chrome.
"""

from __future__ import annotations

import functools
import http.server
import json
import sys
import threading
import time
from pathlib import Path

WEB = Path(__file__).resolve().parent
DIST = WEB / "dist"
SAMPLES = WEB / "samples"
FIXTURES = WEB.parent / "tests" / "fixtures" / "data"
ENGINE_TIMEOUT = 5 * 60 * 1000
CALIBRATION_TIMEOUT = 10 * 60 * 1000


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # keep the report readable
        pass


def serve(directory: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    """A static server on a free local port, like GitHub Pages: files, nothing else."""
    handler = functools.partial(_Quiet, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def answer(page, answers: dict) -> None:
    """Pick the sample home's answers in step 1, by clicking like a person."""
    for qid, value in answers.items():
        fs = page.locator(f'fieldset[data-question="{qid}"]')
        if fs.locator("select").count():
            fs.locator("select").select_option(value)
            continue
        wanted = value if isinstance(value, list) else [value]
        for box in fs.locator("input").all():
            v = box.get_attribute("value")
            if (v in wanted) != box.is_checked():
                box.locator("xpath=..").locator("span").click()


def main() -> int:
    if not (DIST / "index.html").exists():
        sys.exit("no bundle: run build_bundle.py first")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("this tool needs playwright: pip install playwright")
    use_file = "--file" in sys.argv
    shot = (
        sys.argv[sys.argv.index("--screenshot") + 1]
        if "--screenshot" in sys.argv
        else None
    )
    server, base = (None, DIST.as_uri()) if use_file else serve(DIST)
    answers = json.loads((SAMPLES / "home.json").read_text())
    requests: list[str] = []
    marks: dict[str, float] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1100, "height": 900})
        page.on("request", lambda r: requests.append(r.url))
        t0 = time.perf_counter()
        page.goto(f"{base}/index.html")
        page.wait_for_selector("fieldset[data-question=province]")
        marks["step 1 shown"] = time.perf_counter() - t0
        answer(page, answers)
        page.wait_for_selector("#engine.ready", timeout=ENGINE_TIMEOUT)
        marks["engine ready"] = time.perf_counter() - t0
        mode = page.locator("#engine").inner_text()
        page.wait_for_selector("#assume li", timeout=60_000)
        print("Step 1 assumes:", page.locator("#assume li").first.inner_text())
        if shot:
            page.screenshot(path=shot.replace(".png", "-1.png"), full_page=True)
        page.click("#to2")

        if "--formats" in sys.argv:
            fixtures = sorted(FIXTURES.iterdir())
            page.set_input_files("#files", [str(f) for f in fixtures])
            page.wait_for_function(
                f"document.querySelectorAll('.file:not([data-status=busy])').length === {len(fixtures)}",
                timeout=ENGINE_TIMEOUT,
            )
            print("Every ingest fixture, dropped at once:")
            for item in page.locator(".file").all():
                name = item.get_attribute("data-file")
                status = item.get_attribute("data-status")
                msg = item.locator(".file-msg").inner_text()
                print(f"  {status:>13}  {name:28s} {msg[:90]}")
            while page.locator(".file").count():  # each removal re-renders the list
                before = page.locator(".file").count()
                page.locator(".file .remove").first.click()
                page.wait_for_function(
                    f"document.querySelectorAll('.file').length < {before}"
                )

        page.set_input_files(
            "#files",
            [
                str(SAMPLES / "consumo_horario_enero_2026.csv"),
                str(SAMPLES / "estacion_meteo_enero_2026.csv"),
            ],
        )
        station = page.locator('.file[data-file="estacion_meteo_enero_2026.csv"]')
        station.locator(".mapper").wait_for(timeout=ENGINE_TIMEOUT)
        guessed = {
            name: station.locator(f'select[name="{name}"]').input_value()
            for name in ("time", "value", "quantity", "unit")
        }
        print("Column mapper guessed:", guessed)
        assert guessed["quantity"] == "outdoor_temperature", guessed
        assert guessed["value"] == "Temperatura exterior (ºC)", guessed
        station.locator("button.primary").click()
        page.wait_for_selector("#to3:not([disabled])", timeout=ENGINE_TIMEOUT)
        print("Data:", page.locator("#status2").inner_text().replace("\n", " | "))
        if shot:
            page.screenshot(path=shot.replace(".png", "-2.png"), full_page=True)
        page.click("#to3")
        t1 = time.perf_counter()
        page.click("#calibrate")
        page.wait_for_selector("#verdict", timeout=CALIBRATION_TIMEOUT)
        marks["calibration"] = time.perf_counter() - t1
        verdict = page.locator("#verdict").inner_text()
        print(f"\nReport: {verdict}")
        print(page.locator("#report").inner_text()[:1500])
        if shot:
            page.screenshot(path=shot, full_page=True)
        browser.close()
    if server:
        server.shutdown()
    local = ("file://",) if use_file else (base, "data:", "blob:")
    leaks = [u for u in requests if not u.startswith(local)]
    print(
        f"\n{mode}; requests: {len(requests)}, leaving {'the disk' if use_file else 'the server'}: {len(leaks)}"
    )
    for u in leaks:
        print("  LEAK:", u)
    print("timings (s):", {k: round(v, 1) for k, v in marks.items()})
    ok = verdict.lower() in ("good", "usable") and not leaks
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
