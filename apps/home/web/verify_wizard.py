"""Drive the wizard end to end in a real browser, as a householder would.

Serves ``dist/`` from a local static server (as GitHub Pages would), opens it
in Chrome and goes through the three steps with the sample files:

1. answers the onboarding with the sample home's answers (``samples/home.json``),
   and reads "This is your home" and its first estimate;
2. drops the electricity, the weather station's export and the thermometer's
   log on "Your home" (the two logs are read with the column mapper's guess);
3. waits for the analysis, which runs by itself, and reads every area;
4. opens the Demo section, picks a demo home, and checks that going back to
   "Your home" finds it as it was: the sections are independent.

It asserts every request stays on the local server (nothing uploaded,
nothing fetched from elsewhere) and prints the report and the timings.

    python apps/home/web/build_bundle.py
    python apps/home/web/verify_wizard.py [--formats] [--file] [--screenshot PATH]
    python apps/home/web/verify_wizard.py --gas 15dic-15ene   # or 15feb-15mar, 15oct-15nov
    python apps/home/web/verify_wizard.py --lang es           # in Spanish

``--gas PERIOD`` uses the gas home instead (``samples/gas_home/``): its
answers, and the period's electricity, gas bill, water bill and weather
dropped together; it checks the report sets the gas and water bills
against the twin.

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
    """Answer the questions on the onboarding screen, like a person."""
    for qid, value in answers.items():
        fs = page.locator(f'fieldset[data-question="{qid}"]')
        if not fs.count():
            continue  # on another screen
        if fs.locator("select, button[role=combobox]").count():
            continue  # the province: the sample's own is already picked
        wanted = value if isinstance(value, list) else [value]
        for choice in fs.locator(".choice").all():
            box = choice.locator("input, button[role=radio], button[role=checkbox]").first
            v = box.get_attribute("value")
            on = choice.get_attribute("data-on") == "true"
            if (v in wanted) != on:
                choice.click()


def wait_for_answer(page) -> None:
    """The analysis runs by itself; wait until the answer is current."""
    page.wait_for_function(
        "!!document.querySelector('.conf span.on') && "
        "!document.querySelector('.answer').classList.contains('updating')",
        timeout=CALIBRATION_TIMEOUT,
    )


def main() -> int:
    if not (DIST / "index.html").exists():
        sys.exit("no bundle: run build_bundle.py first")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("this tool needs playwright: pip install playwright")
    use_file = "--file" in sys.argv
    lang = sys.argv[sys.argv.index("--lang") + 1] if "--lang" in sys.argv else "en"
    shot = (
        sys.argv[sys.argv.index("--screenshot") + 1]
        if "--screenshot" in sys.argv
        else None
    )
    server, base = (None, DIST.as_uri()) if use_file else serve(DIST)
    gas = sys.argv[sys.argv.index("--gas") + 1] if "--gas" in sys.argv else None
    home = SAMPLES / ("gas_home/home.json" if gas else "home.json")
    answers = json.loads(home.read_text())
    dropped = (
        sorted((SAMPLES / "gas_home" / gas).iterdir())
        if gas
        else [
            SAMPLES / "consumo_horario_enero_2026.csv",
            SAMPLES / "estacion_meteo_enero_2026.csv",
            SAMPLES / "termometro_interior_enero_2026.csv",
        ]
    )
    requests: list[str] = []
    errors: list[str] = []
    marks: dict[str, float] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1200, "height": 1000})
        page.on("request", lambda r: requests.append(r.url))
        page.on("pageerror", lambda e: errors.append(str(e)))
        t0 = time.perf_counter()
        page.goto(f"{base}/index.html")
        page.wait_for_selector("#start")
        page.select_option("#lang", lang)
        marks["welcome shown"] = time.perf_counter() - t0
        page.wait_for_selector("#engine.ready", timeout=ENGINE_TIMEOUT)
        marks["engine ready"] = time.perf_counter() - t0
        mode = page.locator("#engine").inner_text()
        print(
            "Sections:",
            [b.inner_text() for b in page.locator("nav.sections button").all()],
        )

        page.click("#start")
        for _ in range(3):
            answer(page, answers)
            page.locator(".actions button.primary").click()
        page.wait_for_selector(".estimate-row", timeout=ENGINE_TIMEOUT)
        print(
            "This is your home:",
            page.locator("dl.summary").inner_text().replace("\n", " | "),
        )
        print("First estimate:", page.locator(".estimate-row p").inner_text())
        page.locator(".actions button.primary").click()
        page.wait_for_selector(".cards .card")
        print("Next best step:", page.locator(".banner.next p").last.inner_text())

        if "--formats" in sys.argv:
            fixtures = sorted(FIXTURES.iterdir())
            page.set_input_files("#files", [str(f) for f in fixtures])
            page.wait_for_function(
                f"document.querySelectorAll('.file').length >= {len(fixtures)}",
                timeout=ENGINE_TIMEOUT,
            )
            print("Every ingest fixture, dropped at once:")
            for item in page.locator(".file").all():
                name = item.get_attribute("data-file")
                status = item.get_attribute("data-status")
                msg = item.locator(".file-msg").inner_text()
                print(f"  {status:>13}  {name:28s} {msg[:90]}")
            while page.locator(".file .remove").count():
                before = page.locator(".file .remove").count()
                page.locator(".file .remove").first.click()
                page.wait_for_function(
                    f"document.querySelectorAll('.file .remove').length < {before}"
                )

        t1 = time.perf_counter()
        page.set_input_files("#files", [str(f) for f in dropped])
        wait_for_answer(page)
        marks["analysis"] = time.perf_counter() - t1
        for c in page.locator(".card").all():
            print(
                f"  card {c.get_attribute('data-kind'):12s} {c.locator('.chip').inner_text()}"
            )
        letter = page.locator(".letter").first.inner_text()
        print(
            f"\nAnswer: {letter} · {page.locator('.money').inner_text()} · {page.locator('.tile .small').last.inner_text()}"
        )
        print(page.locator(".answer-text").inner_text())
        for area in ("money", "heating", "whatif", "trust", "months"):
            page.click(f'[data-tab="{area}"]')
            print(
                f"  [{area}]",
                page.locator(".panel[data-state=active]")
                .inner_text()
                .replace("\n", " | ")[:280],
            )
        if shot:
            page.screenshot(path=shot, full_page=True)

        # the sections are independent: a demo does not disturb this home
        page.click('[data-section="demo"]')
        page.wait_for_selector(".demo-card")
        page.wait_for_timeout(400)
        page.click('[data-example="gas_dec_jan"]')
        wait_for_answer(page)
        print(
            "\nDemo:",
            page.locator("main h1").inner_text(),
            "·",
            page.locator(".banner.demo").inner_text().split("\n")[0],
        )
        page.click('[data-section="home"]')
        page.wait_for_selector(".cards .card")
        back = page.locator(".letter").first.inner_text()
        print(
            "Back in your home:",
            page.locator("main h1").inner_text(),
            "·",
            back,
            "· files:",
            page.locator(".card .file").count(),
            "· demo banner:",
            page.locator(".banner.demo").count(),
        )
        assert back == letter, "the demo changed the householder's own answer"
        assert page.locator(".banner.demo").count() == 0
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
    for e in errors:
        print("  PAGE ERROR:", e)
    print("timings (s):", {k: round(v, 1) for k, v in marks.items()})
    return 0 if not leaks and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
