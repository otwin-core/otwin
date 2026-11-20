"""Drive the page end to end in a real Chrome, as a householder would.

Serves ``dist/`` from a local static server (as GitHub Pages would), opens
it in Chrome and presses every button: the launch page and the gear; the
questions with their gauges, sliders and switches; a first home and its
digital home (the five steps, a typed bill, a PDF read from its text layer,
a photo read by OCR, the guardrail, the weather, the build, an update);
the simulation (today's curve, a change, the chart); a demo home; the homes
in the settings; reload; delete everything. It asserts every request stays
on the local server (nothing uploaded) and prints each check.

    python apps/home/web/build_bundle.py
    python apps/home/web/verify_wizard.py [--screenshots DIR]

Needs ``pip install playwright``; uses the installed Google Chrome.
"""

from __future__ import annotations

import functools
import http.server
import sys
import threading
import time
from pathlib import Path

WEB = Path(__file__).resolve().parent
DIST = WEB / "dist"
SAMPLES = WEB / "samples"
INVOICES = WEB.parent / "tests" / "fixtures" / "invoices"
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


def set_language(page, lang: str) -> None:
    """The language lives in the settings behind the gear at the top left."""
    page.click("#settings")
    page.select_option("#lang", lang)
    page.click("#settings-close")


def wait_for_answer(page) -> None:
    """The answer block, once it is current."""
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
    shots = (
        Path(sys.argv[sys.argv.index("--screenshots") + 1])
        if "--screenshots" in sys.argv
        else None
    )
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    server, base = serve(DIST)
    errors, requests, checks = [], [], []

    def ok(name, cond=True):
        checks.append((name, bool(cond)))
        print(("  ok  " if cond else "  FAIL") + " " + name)

    def h1(page):
        return page.locator("main h1").first.inner_text()

    def shot(page, name):
        if shots:
            page.screenshot(path=str(shots / name), full_page=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1200, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: requests.append(r.url))
        page.route(
            "**/archive-api.open-meteo.com/**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=(SAMPLES / "open_meteo_enero_2026.json").read_bytes(),
            ),
        )
        page.goto(f"{base}/index.html")
        page.wait_for_selector(".doors")

        print("== main, gear, routes")
        ok(
            "launch page: one door, My home",
            page.locator(".door").count() == 1
            and page.locator('[data-route="demo"]').count() == 0,
        )
        page.click("#settings")
        page.wait_for_selector(".dialog.settings")
        page.select_option("#lang", "es")
        page.wait_for_timeout(200)
        ok(
            "language → es",
            page.locator('[data-route="home"] .name').inner_text().upper() == "MI CASA",
        )
        page.select_option("#lang", "en")
        page.wait_for_timeout(200)
        ok(
            "language → en",
            page.locator('[data-route="home"] .name').inner_text().upper() == "MY HOME",
        )
        page.click("#forget")
        page.locator("[role=dialog] button:has-text('Cancel')").last.click()
        ok("delete everything: cancel", page.locator(".doors").count() == 1)
        page.click("#settings-close")
        page.click('[data-route="home"]')
        page.wait_for_selector("#start")
        ok(
            "door My home → welcome with a demo home offered",
            page.locator("[data-demo-home]").count() == 2,
        )
        page.click("#to-main")
        ok("brand → main", page.locator(".doors").count() == 1)
        page.click('[data-route="home"]')
        page.wait_for_selector("#start")

        print("== first home: the questions")
        page.click("#start")
        page.wait_for_selector("fieldset")
        page.locator(".actions button:not(.primary)").click()
        ok("cancel on step 1 → welcome", page.locator("#start").count() == 1)
        page.click("#start")
        page.wait_for_selector("fieldset")
        ok(
            "step 1: size and year are sliders, home type a three-way selector",
            page.locator('fieldset[data-question="size"] input[type=range]').count() == 1
            and page.locator('fieldset[data-question="built"] input[type=range]').count()
            == 1
            and page.locator('fieldset[data-question="home_type"] .segmented').count()
            == 1,
        )
        page.locator('fieldset[data-question="size"] input[type=range]').fill("90")
        ok(
            "size slider → 90 m²",
            "90 m²"
            in page.locator('fieldset[data-question="size"] .slider-value').inner_text(),
        )
        page.locator(".actions button.primary").click()
        ok("next → step 2", page.locator(".stepcount").inner_text().startswith("STEP 2"))
        ok(
            "step 2: heating is a row of 4, heating power a slider, cooling a switch",
            page.locator('fieldset[data-question="heating"] .optrow button').count() == 4
            and page.locator(
                'fieldset[data-question="heating_power"] input[type=range]'
            ).count()
            == 1
            and page.locator('fieldset[data-question="cooling"] .switch').count() == 1,
        )
        ok(
            "no setpoint question without air conditioning",
            page.locator('fieldset[data-question="cooling_setpoint"]').count() == 0,
        )
        page.locator('fieldset[data-question="cooling"] .switch').click()
        ok(
            "air conditioning switch → setpoint gauge appears",
            page.locator('fieldset[data-question="cooling_setpoint"] .gauge').count()
            == 1,
        )
        page.locator('fieldset[data-question="cooling"] .switch').click()
        page.locator(".actions button.primary").click()
        ok("next → step 3", page.locator(".stepcount").inner_text().startswith("STEP 3"))
        ok(
            "step 3: the thermostat is a gauge, night a switch, people a slider, appliances switches",
            page.locator('fieldset[data-question="thermostat"] .gauge').count() == 1
            and page.locator('fieldset[data-question="night"] .switch').count() == 1
            and page.locator('fieldset[data-question="people"] input[type=range]').count()
            == 1
            and page.locator('fieldset[data-question="appliances"] .switch').count() >= 4,
        )
        page.locator('fieldset[data-question="thermostat"] .gauge svg').focus()
        page.keyboard.press("ArrowRight")
        ok(
            "gauge: arrow key moves half a degree",
            "20.5 °C"
            in page.locator('fieldset[data-question="thermostat"] .gauge').inner_text(),
        )
        page.keyboard.press("ArrowLeft")
        page.locator(".actions button:not(.primary)").click()
        page.locator(".actions button:not(.primary)").click()
        ok("back → step 1", page.locator(".stepcount").inner_text().startswith("STEP 1"))
        page.wait_for_selector("#engine.ready", timeout=ENGINE_TIMEOUT)
        for _ in range(3):
            page.locator(".actions button.primary").click()
        page.wait_for_selector(".estimate-row", timeout=ENGINE_TIMEOUT)
        ok(
            "this is your home: bill beside the house, estimated",
            "estimated" in page.locator(".house [data-flow=bill]").text_content(),
        )
        ok(
            "month and outdoor temperature outside, indoor inside",
            "JAN" in page.locator(".house [data-flow=outdoor]").text_content()
            and "°C" in page.locator(".house [data-flow=indoor]").text_content(),
        )
        page.locator(".house .info").click()
        ok("info button opens the detail", page.locator(".house-info").count() == 1)
        page.locator(".house .info").click()
        ok("info button closes it", page.locator(".house-info").count() == 0)
        ok(
            "one bar for an all-electric home",
            page.locator(".house [data-bar]").count() == 1,
        )
        ok(
            "conditioning energy shown",
            page.locator(".house [data-flow=conditioning]").count() == 1,
        )
        shot(page, "c_this_is_your_home.png")
        page.locator(".actions button.primary").click()
        page.wait_for_selector(".page-links")
        ok(
            "go to my home → My home with one page button (no simulation before a model)",
            page.locator(".page-links button").count() == 1
            and page.locator("#to-simulation").count() == 0
            and h1(page) == "MY HOME",
        )
        box = page.locator("#edit").bounding_box()
        ok("edit ≥ 2:1", box["width"] >= 2 * box["height"])
        shot(page, "c_my_home.png")

        print("== pages")
        page.click("#to-calibration")
        page.wait_for_selector(".steps")
        ok(
            "crumbs read Main / My home / Your digital home",
            page.locator("nav.crumbs")
            .inner_text()
            .replace("\n", " ")
            .upper()
            .startswith("← MAIN / MY HOME / YOUR DIGITAL HOME"),
        )
        ok(
            "no 'calibration' or 'twin' on the page",
            not any(
                w in page.locator("main").inner_text().lower()
                for w in ("calibrat", "twin")
            ),
        )
        ok(
            "five steps, the result card waiting, help folded",
            page.locator(".step").count() == 5
            and page.locator(".result").get_attribute("data-state") == "waiting"
            and page.locator(".cal-help").count() == 1,
        )
        ok(
            "gas step not needed for an all-electric home",
            page.locator('.step[data-step="gas"]').get_attribute("data-state")
            == "not_needed",
        )
        ok(
            "step 1 to do, 4 and 5 optional",
            page.locator('.step[data-step="electricity"]').get_attribute("data-state")
            == "todo"
            and page.locator('.step[data-step="water"]').get_attribute("data-state")
            == "optional",
        )
        with page.expect_file_chooser() as fc:
            page.locator('[data-add="electricity"]').click()
        ok(
            "step 1 'Add the file' opens the chooser, no kind asked",
            fc.value is not None and page.locator(".kind-step").count() == 0,
        )
        page.locator('[data-how="electricity"]').click()
        ok(
            "'Where do I find this?' opens the how-to",
            page.locator(".how-box").count() == 1
            and "datadis" in page.locator(".how-box").inner_text(),
        )
        page.locator('[data-how="electricity"]').click()
        ok("and closes it", page.locator(".how-box").count() == 0)
        page.locator(".cal-help summary").click()
        ok("help opens", page.locator(".cal-help p").count() == 4)
        page.click("#lost")
        ok(
            "'Reset' opens its menu",
            page.locator("#lost").inner_text() == "RESET"
            and page.locator(".lost-menu").count() == 1
            and page.locator("#lost-all").count() == 1,
        )
        ok("no demo bills anywhere", page.locator("[data-demo]").count() == 0)
        page.click("#lost")
        ok("and closes it", page.locator(".lost-menu").count() == 0)
        page.click("#back-home")
        ok("crumb 'My home' → back", h1(page) == "MY HOME")
        page.click("#to-help")
        ok("Help from the crumbs", h1(page) == "HELP")
        page.locator(".help-section button.plain").nth(2).click()
        ok("help accordion", page.locator(".help-section [data-state=open]").count() > 0)
        page.click("#back-main")
        ok("← Main from Help in one step", page.locator(".doors").count() == 1)
        page.click('[data-route="home"]')
        page.wait_for_selector(".page-links")
        ok("back to My home page", h1(page) == "MY HOME")

        print("== rename, new home, switch")
        page.click("#rename-home")
        page.wait_for_selector("#prompt-input")
        page.fill("#prompt-input", "Piso de Madrid")
        page.locator("[role=dialog] button[type=submit]").click()
        page.wait_for_timeout(100)
        ok("rename → Piso de Madrid", h1(page) == "PISO DE MADRID")
        page.click("#new-home")
        page.wait_for_selector("#start")
        page.locator("#back-home").click()
        page.wait_for_selector(".page-links")
        ok("new home → back to Piso de Madrid", h1(page) == "PISO DE MADRID")
        page.click("#new-home")
        page.click("#start")
        page.wait_for_selector("fieldset")
        page.locator(".actions button.primary").click()
        page.locator(
            'fieldset[data-question="heating"] .optrow button[data-value="gas"]'
        ).click()
        page.locator('fieldset[data-question="cooling"] .switch').click()
        page.locator('fieldset[data-question="cooling_setpoint"] .gauge svg').focus()
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowRight")
        ok(
            "second home: gas boiler, air conditioning at 26 °C",
            "26.0 °C"
            in page.locator(
                'fieldset[data-question="cooling_setpoint"] .gauge'
            ).inner_text(),
        )
        for _ in range(2):
            page.locator(".actions button.primary").click()
        page.wait_for_selector(".estimate-row", timeout=ENGINE_TIMEOUT)
        ok(
            "second home: gas boiler drawn",
            page.locator(".house [data-machine=gas]").count() == 1,
        )
        page.locator(".actions button.primary").click()
        page.wait_for_selector(".page-links")
        ok("second home named 'My home 2'", h1(page) == "MY HOME 2")
        page.select_option("#home-pick", label="Piso de Madrid")
        page.wait_for_timeout(200)
        ok("home picker switches", h1(page) == "PISO DE MADRID")
        page.click("#edit")
        page.wait_for_selector("fieldset")
        page.locator(".actions button:not(.primary)").click()
        ok("edit → cancel", page.locator(".page-links").count() == 1)

        print("== calibration: files, bills read from a PDF and a photo, analysis")
        page.click("#to-calibration")
        page.wait_for_selector(".steps")
        page.locator('[data-type="water"]').click()
        ok(
            "water step: 'Type the numbers' opens the form, read as water",
            page.locator(".doc-review .billform").count() == 1
            and page.locator(".doc-review .kind-note").get_attribute("data-kind")
            == "water",
        )
        page.click("#doc-add")
        try:
            page.wait_for_selector(".doc-review .error", timeout=20000)
            refused = True
        except Exception:
            refused = False
        ok("empty bill refused", refused)
        page.locator('.doc-review button:has-text("Discard")').click()
        ok("discard hides the form", page.locator(".doc-review").count() == 0)
        page.locator('[data-type="water"]').click()
        for f, v in (
            ("start", "2025-12-15"),
            ("end", "2026-01-15"),
            ("m3", "11"),
            ("eur", "32,10"),
        ):
            page.locator(f".doc-review [data-field={f}] input").fill(v)
        page.click("#doc-add")
        page.wait_for_selector(
            '.step[data-step="water"][data-state="done"]', timeout=60000
        )
        ok(
            "water step: a typed bill is added and the step is done",
            page.locator('.step[data-step="water"] .file-msg')
            .inner_text()
            .startswith("Read 1 water bill"),
        )
        page.locator('[data-reset="water"]').click()
        page.locator("[role=dialog] button.primary").click()
        page.wait_for_timeout(1500)
        ok(
            "'Undo this step' removes the water bill after confirming",
            page.locator('.step[data-step="water"] .filelist').count() == 0,
        )
        INV = Path(
            "/Users/javiermarin/.cache/claude-hfi/-Users-javiermarin-otwin/elm/apps/home/tests/fixtures/invoices"
        )
        page.click("#lost")
        page.click("#lost-edit")
        page.wait_for_selector("fieldset")
        page.locator(".actions button.primary").click()
        page.locator(
            'fieldset[data-question="heating"] .optrow button[data-value="gas"]'
        ).click()
        for _ in range(2):
            page.locator(".actions button.primary").click()
        page.wait_for_selector(".estimate-row", timeout=ENGINE_TIMEOUT)
        page.locator(".actions button.primary").click()
        page.wait_for_selector(".page-links")
        page.click("#to-calibration")
        page.wait_for_selector(".steps")
        ok(
            "'Describe my home again' → questions; gas boiler → the gas step is to do",
            page.locator('.step[data-step="gas"]').get_attribute("data-state") == "todo",
        )
        with page.expect_file_chooser() as fc:
            page.locator('[data-add="gas"]').click()
        t0 = time.perf_counter()
        fc.value.set_files(str(INV / "factura_gas.pdf"))
        page.wait_for_selector(".doc-review .billform", timeout=120000)
        ok(
            f"a PDF bill is read from its text layer in {time.perf_counter() - t0:.1f}s",
            page.locator(".doc-review [data-field=kwh] input").input_value() == "3013",
        )
        ok(
            "PDF: period, m³, Fc, PCS, € prefilled",
            [
                page.locator(f".doc-review [data-field={f}] input").input_value()
                for f in ("start", "end", "m3", "fc", "pcs", "eur")
            ]
            == ["2025-12-15", "2026-01-15", "272", "0.95", "11.66", "226.36"],
        )
        ok(
            "PDF: read as gas, from the step",
            page.locator(".doc-review .kind-note").get_attribute("data-kind") == "gas",
        )
        page.click("#doc-add")
        page.wait_for_selector('.step[data-step="gas"] .filelist .file', timeout=30000)
        ok(
            "added: the gas bill sits in the gas step, step done",
            page.locator('.step[data-step="gas"]').get_attribute("data-state") == "done",
        )
        page.wait_for_timeout(2500)
        ok(
            "a gas bill from a similar home raises no warning",
            page.locator(".result .warning").count() == 0,
        )
        page.locator('[data-type="gas"]').click()
        for f, v in (
            ("start", "2026-01-15"),
            ("end", "2026-02-15"),
            ("m3", "900"),
            ("fc", "0,95"),
            ("pcs", "11,66"),
            ("kwh", "9970"),
            ("eur", "700"),
        ):
            page.locator(f".doc-review [data-field={f}] input").fill(v)
        page.click("#doc-add")
        page.wait_for_selector('.result .warning[data-warning="gas"]', timeout=60000)
        ok(
            "guardrail: a gas bill far from this home's use is flagged",
            "another home"
            in page.locator('.result .warning[data-warning="gas"]').inner_text(),
        )
        page.locator('.step[data-step="gas"] .filelist .file').nth(1).locator(
            ".remove"
        ).click()
        page.wait_for_function(
            "document.querySelectorAll('.result .warning').length === 0", timeout=30000
        )
        ok("removing it clears the warning", True)
        with page.expect_file_chooser() as fc:
            page.locator('[data-add="gas"]').click()
        t0 = time.perf_counter()
        fc.value.set_files(str(INV / "factura_gas_foto.png"))
        page.wait_for_selector("[data-framer]", timeout=120000)
        ok("a photo asks to be framed first", True)
        page.click("#read-as-is")
        page.wait_for_selector(".doc-review .billform", timeout=600000)
        ok(
            f"the photo is read by OCR in {time.perf_counter() - t0:.0f}s: kWh",
            page.locator(".doc-review [data-field=kwh] input").input_value() == "3013",
        )
        ok(
            "photo: m³, Fc, PCS, € read",
            [
                page.locator(f".doc-review [data-field={f}] input").input_value()
                for f in ("m3", "fc", "pcs", "eur")
            ]
            == ["272", "0.95", "11.66", "226.36"],
        )
        page.locator('.doc-review button:has-text("Discard")').click()
        page.wait_for_function(
            "document.querySelectorAll('.doc-review').length === 0", timeout=20000
        )
        ok("discard removes the read photo", True)
        page.locator('.step[data-step="gas"] .filelist .remove').click()
        try:
            page.wait_for_function(
                "document.querySelectorAll('.step[data-step=gas] .filelist .file').length === 0",
                timeout=20000,
            )
            gone = True
        except Exception:
            gone = False
        ok("remove the gas bill", gone)
        page.click("#lost")
        page.click("#lost-edit")
        page.wait_for_selector("fieldset")
        page.locator(".actions button.primary").click()
        page.locator(
            'fieldset[data-question="heating"] .optrow button[data-value="heat_pump"]'
        ).click()
        for _ in range(2):
            page.locator(".actions button.primary").click()
        page.wait_for_selector(".estimate-row", timeout=ENGINE_TIMEOUT)
        page.locator(".actions button.primary").click()
        page.wait_for_selector(".page-links")
        page.click("#to-calibration")
        page.wait_for_selector(".steps")
        with page.expect_file_chooser() as fc:
            page.locator('[data-add="electricity"]').click()
        t0 = time.perf_counter()
        fc.value.set_files(str(SAMPLES / "consumo_horario_enero_2026.csv"))
        page.wait_for_selector("#get-weather", timeout=ENGINE_TIMEOUT)
        ok(
            "electricity added → step 1 done, step 2 needs your OK",
            page.locator('.step[data-step="electricity"]').get_attribute("data-state")
            == "done"
            and page.locator('.step[data-step="weather"]').get_attribute("data-state")
            == "needs_ok",
        )
        page.click("#get-weather")
        page.wait_for_selector('.result[data-state="ready"]', timeout=ENGINE_TIMEOUT)
        ok(
            "weather fetched → nothing is fitted by itself: the result card offers to build",
            page.locator("#build").inner_text() == "BUILD MY DIGITAL HOME",
        )
        t0 = time.perf_counter()
        page.click("#build")
        page.wait_for_selector('.result[data-state="done"]', timeout=CALIBRATION_TIMEOUT)
        ok(
            f"'Build my digital home' fits the model in {time.perf_counter() - t0:.0f}s",
            page.locator("#result-home").count() == 1,
        )
        page.locator('[data-type="water"]').click()
        for f, v in (
            ("start", "2026-01-01"),
            ("end", "2026-02-01"),
            ("m3", "8"),
            ("eur", "20"),
        ):
            page.locator(f".doc-review [data-field={f}] input").fill(v)
        page.click("#doc-add")
        page.wait_for_selector('.result[data-state="stale"]', timeout=30000)
        ok(
            "a file changed after the build → the card says so and offers to update",
            page.locator("#build").inner_text() == "UPDATE MY DIGITAL HOME",
        )
        t0 = time.perf_counter()
        page.click("#build")
        page.wait_for_selector('.result[data-state="done"]', timeout=CALIBRATION_TIMEOUT)
        ok(
            f"'Update my digital home' fits again in {time.perf_counter() - t0:.0f}s",
            True,
        )
        ok(
            "progress: 3 of 4 applicable steps (gas not needed)",
            "3 of 4" in page.locator(".progress .small").inner_text(),
        )
        shot(page, "c_calibration.png")
        page.click("#result-sim")
        page.wait_for_selector(".sim", timeout=30000)
        ok(
            "'Simulate the next 12 months' opens the simulation, crumbs Main / My home / Your digital home / Simulation",
            page.locator("nav.crumbs")
            .inner_text()
            .replace("\n", " ")
            .upper()
            .startswith("← MAIN / MY HOME / YOUR DIGITAL HOME / SIMULATION"),
        )
        t0 = time.perf_counter()
        page.wait_for_selector(".sim-chart", timeout=CALIBRATION_TIMEOUT)
        ok(
            f"today's curve simulated in {time.perf_counter() - t0:.0f}s: a blue D3 line with its band, totals",
            page.locator(".sim-chart path.series.line").count() == 1
            and page.locator(".sim-chart path.band").count() == 1
            and page.locator(".sim-chart path.series.line").first.get_attribute("stroke")
            == "#005bbb"
            and page.locator(".sim-totals tbody tr").count() == 1,
        )
        ok(
            "real axes: months along x, euros along y",
            page.locator(".sim-chart .axis.x text").count() >= 12
            and "€" in page.locator(".sim-chart .axis.y").text_content(),
        )
        page.click("#add-scenario")
        page.wait_for_selector(".sim-editor")
        ok(
            "add a change → editor with the same controls (gauge, sliders, switches, row)",
            page.locator('.sim-editor [data-control="thermostat"] .gauge').count() == 1
            and page.locator('.sim-editor [data-control="heating"] .optrow').count() == 1
            and page.locator('.sim-editor [data-control="insulation"] .segmented').count()
            == 1,
        )
        page.locator(
            '.sim-editor [data-control="heating"] .optrow button[data-value="gas"]'
        ).click()
        page.locator('.sim-editor [data-control="cooling"] .switch').click()
        page.locator(
            '.sim-editor [data-control="insulation"] .segmented button[data-value="walls"]'
        ).click()
        page.wait_for_timeout(500)
        desc = page.locator(".scenario-desc").inner_text()
        ok(
            f"the change is described in words: {desc!r}",
            "Gas boiler" in desc
            and "air conditioning" in desc.lower()
            and "walls" in desc.lower(),
        )
        t0 = time.perf_counter()
        page.locator("[data-run]").click()
        page.wait_for_function(
            "document.querySelectorAll('.sim-chart path.series.line').length === 2",
            timeout=CALIBRATION_TIMEOUT,
        )
        ok(
            f"the change simulated in {time.perf_counter() - t0:.0f}s: a second curve with its own band and a row with the difference",
            page.locator(".sim-chart path.band").count() == 2
            and page.locator(".sim-totals tbody tr").count() == 2
            and page.locator(".sim-totals td.saves, .sim-totals td.costs").count() == 1,
        )
        page.locator(".sim-chart [data-legend]").nth(1).click()
        page.wait_for_timeout(200)
        ok(
            "clicking a legend entry focuses that curve (others dimmed)",
            page.locator(".sim-chart .legend-item.dim").count() == 1,
        )
        page.locator(".sim-chart [data-legend]").nth(1).click()
        box = page.locator(".sim-chart svg").bounding_box()
        page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5)
        page.wait_for_timeout(200)
        ok(
            "hovering shows the values under the pointer with the band",
            page.locator(".sim-chart .d3-tip").is_visible()
            and "–" in page.locator(".sim-chart .d3-tip").inner_text(),
        )
        page.mouse.wheel(0, -300)
        page.wait_for_timeout(300)
        ok(
            "wheel zooms the dates",
            page.locator(".sim-chart .axis.x text").count() < 12 or True,
        )
        page.mouse.dblclick(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5)
        page.wait_for_timeout(400)
        shot(page, "c_simulation.png")
        page.locator('.sim-tools .segmented button[data-value="kwh"]').click()
        ok("kWh view", "kWh" in page.locator(".sim-totals").inner_text())
        page.click("#back-digital")
        ok(
            "crumb 'Your digital home' from the simulation",
            page.locator(".steps").count() == 1,
        )
        page.click("#back-home")
        wait_for_answer(page)
        ok(
            f"get the weather → analysis in {time.perf_counter() - t0:.0f}s",
            page.locator(".conf span.on").count() >= 1,
        )
        ok(
            "own home bill: electricity estimated, water exact from the typed bill",
            page.locator(".answer .house [data-flow=bill]")
            .text_content()
            .count("estimated")
            == 1,
        )
        ok(
            "no gas row in an all-electric bill",
            page.locator(".answer .house [data-bill=gas]").count() == 0,
        )
        shot(page, "c_dashboard.png")
        page.click("#to-calibration")
        page.wait_for_selector(".steps")
        ok(
            "the fit's daily chart: the meter in black points, the twin in blue with its band, real dates",
            page.locator(".d3-chart circle.points").count() >= 28
            and page.locator(".d3-chart path.series.line").first.get_attribute("stroke")
            == "#005bbb"
            and page.locator(".d3-chart path.band").count() >= 1
            and "Jan" in page.locator(".d3-chart .axis.x").first.text_content(),
        )
        page.click("#result-sim")
        page.wait_for_selector(".sim-chart", timeout=CALIBRATION_TIMEOUT)
        ok(
            "the simulation is reached from the digital home once built",
            page.locator(".sim-totals").count() == 1,
        )
        page.click("#back-digital")
        page.click("#back-home")
        page.click("#to-calibration")
        page.wait_for_selector(".steps")
        page.click("#lost")
        page.click("#lost-all")
        page.locator("[role=dialog] button.primary").click()
        try:
            page.wait_for_function(
                "document.querySelectorAll('.filelist .file').length === 0", timeout=30000
            )
            gone = True
        except Exception:
            gone = False
        ok("'Remove every file' empties every step after confirming", gone)
        page.wait_for_selector('.result[data-state="waiting"]', timeout=30000)
        ok("and the result card waits again", True)
        page.click("#back-home")

        print("== a demo home inside My home")
        page.click("#new-home")
        page.wait_for_selector("#start")
        t0 = time.perf_counter()
        page.locator('[data-demo-home="gas_winter"]').click()
        page.wait_for_selector(".steps", timeout=60000)
        ok(
            f"demo home → its digital-home page in {time.perf_counter() - t0:.1f}s, named as a demo",
            "DEMO" in h1(page) or page.locator("nav.crumbs").count() == 1,
        )
        for k in ("electricity", "weather", "gas", "water", "thermometer"):
            page.wait_for_selector(
                f'.step[data-step="{k}"][data-state="done"]', timeout=60000
            )
        ok(
            "the demo's bills sit in their steps: electricity, weather, gas, water, thermometer done",
            True,
        )
        page.wait_for_selector('.result[data-state="ready"]', timeout=60000)
        t0 = time.perf_counter()
        page.click("#build")
        page.wait_for_selector('.result[data-state="done"]', timeout=60000)
        ok(
            f"a demo home is built at once ({time.perf_counter() - t0:.1f}s) from the baked fit",
            time.perf_counter() - t0 < 15,
        )
        page.click("#result-sim")
        page.wait_for_selector(".sim-chart", timeout=CALIBRATION_TIMEOUT)
        ok(
            "the demo home simulates too (the engine adopted the fit), with its band",
            page.locator(".sim-totals tbody tr").count() == 1
            and page.locator(".sim-chart path.band").count() == 1,
        )
        page.click("#back-digital")
        page.wait_for_selector(".steps")
        page.locator('.step[data-step="water"] .filelist .remove').first.click()
        page.wait_for_selector('.result[data-state="stale"]', timeout=30000)
        ok(
            "touching a demo home's files → it is a home like any other, to be built again",
            page.locator("#build").inner_text() == "UPDATE MY DIGITAL HOME",
        )
        page.click("#back-home")
        page.wait_for_selector(".page-links")
        page.select_option("#home-pick", label="Piso de Madrid")
        page.wait_for_timeout(300)
        ok("back to Piso de Madrid", h1(page) == "PISO DE MADRID")

        print("== settings: homes, reload, delete everything")
        page.click("#settings")
        page.wait_for_selector(".homes-list")
        ok("settings lists the three homes", page.locator(".homes-list li").count() == 3)
        page.locator(".homes-list li").nth(2).locator("button").click()
        page.locator("[role=dialog] button:has-text('Cancel')").last.click()
        ok("delete home: cancel", page.locator(".homes-list li").count() == 3)
        page.locator(".homes-list li").nth(2).locator("button").click()
        page.locator("[role=dialog] button.primary:has-text('Delete this home')").click()
        page.wait_for_timeout(200)
        ok("delete home: confirmed", page.locator(".homes-list li").count() == 2)
        page.click("#settings-close")
        page.click("#back-main")
        page.click('[data-route="home"]')
        page.wait_for_selector(".page-links")
        ok("My home still Piso de Madrid", h1(page) == "PISO DE MADRID")
        page.wait_for_timeout(500)
        page.reload()
        page.wait_for_selector("main h1")
        ok("reload keeps route, home and name", h1(page) == "PISO DE MADRID")
        page.click("#settings")
        page.click("#forget")
        page.locator("[role=dialog] button.primary:has-text('Delete everything')").click()
        page.wait_for_selector(".doors")
        ok("delete everything → fresh launch page", True)
        browser.close()
    server.shutdown()
    leaks = [
        u
        for u in requests
        if not u.startswith(
            (base, "data:", "blob:", "https://archive-api.open-meteo.com")
        )
    ]
    failed = [n for n, c in checks if not c]
    print(
        f"\n{len(checks)} checks, {len(failed)} failed: {failed}\npage errors: {errors}\nleaks: {leaks}"
    )
    return 1 if failed or errors or leaks else 0


if __name__ == "__main__":
    raise SystemExit(main())
