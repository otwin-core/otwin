/* The Otwin Home wizard: three steps, no framework.
 *
 * Step 1 renders from OTWIN_QUESTIONS (baked from survey.QUESTIONS at build
 * time), so it appears at once while the engine starts in the background.
 * Steps 2 and 3 talk to the engine through OtwinHome.call; files are read
 * as bytes and handed to it, never to a server. Text from files and from
 * the engine is only ever set as textContent.
 */
"use strict";

(() => {
  const Q = OTWIN_QUESTIONS;
  const $ = (id) => document.getElementById(id);
  const answers = {};
  const files = new Map(); // id -> summary from the engine
  let engineReady = false;
  let fileCounter = 0;

  /* ------------------------------------------------------------ helpers */
  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (v === true) node.setAttribute(k, "");
      else if (v !== false && v != null) node.setAttribute(k, v);
    }
    for (const c of children.flat()) {
      if (c == null) continue;
      node.append(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return node;
  }
  const timezoneOf = () =>
    (Q.provinces.find((p) => p.value === answers.province) || {}).timezone || "Europe/Madrid";

  /* ------------------------------------------------------------ the engine */
  const engine = $("engine");
  OtwinHome.start((s) => (engine.textContent = `Engine: ${s}`))
    .then((info) => {
      engineReady = true;
      engine.textContent =
        info.mode === "worker"
          ? "Engine ready, running in this browser"
          : "Engine ready, running in this page";
      engine.classList.add("ready");
      refreshAssumptions();
    })
    .catch((e) => {
      engine.textContent = `The engine could not start: ${e.message}`;
      engine.classList.add("failed");
    });

  /* ------------------------------------------------------------ steps */
  function showStep(n, scroll = true) {
    for (const i of [1, 2, 3]) $(`step${i}`).hidden = i !== n;
    for (const li of $("steps").children) {
      const i = Number(li.dataset.step);
      li.classList.toggle("active", i === n);
      li.classList.toggle("done", i < n);
    }
    if (scroll) window.scrollTo({ top: $("steps").offsetTop - 16, behavior: "smooth" });
    if (n === 2) refreshStatus();
  }
  $("to2").addEventListener("click", () => showStep(2));
  $("back1").addEventListener("click", () => showStep(1));
  $("to3").addEventListener("click", () => showStep(3));
  $("back2").addEventListener("click", () => showStep(2));

  /* ------------------------------------------------------------ step 1 */
  function renderSurvey() {
    const form = $("survey");
    form.replaceChildren();
    for (const q of Q.questions) {
      const fs = el("fieldset", { "data-question": q.id }, el("legend", { text: q.label }));
      if (q.help) fs.append(el("p", { class: "help", text: q.help }));
      if (q.kind === "single" && q.options.length > 8) {
        const sel = el("select", { name: q.id, "aria-label": q.label });
        for (const o of q.options) {
          sel.append(el("option", { value: o.value, selected: o.value === answers[q.id] }, o.label));
        }
        sel.addEventListener("change", () => setAnswer(q.id, sel.value));
        fs.append(sel);
      } else {
        const box = el("div", { class: "choices" });
        for (const o of q.options) {
          const multi = q.kind === "multi";
          const checked = multi ? answers[q.id].includes(o.value) : answers[q.id] === o.value;
          const input = el("input", {
            type: multi ? "checkbox" : "radio",
            name: q.id,
            value: o.value,
            checked,
          });
          input.addEventListener("change", () => {
            if (multi) {
              const picked = [...form.querySelectorAll(`input[name="${q.id}"]:checked`)];
              setAnswer(q.id, picked.map((i) => i.value));
            } else setAnswer(q.id, o.value);
          });
          box.append(el("label", { class: "choice" }, input, el("span", { text: o.label })));
        }
        fs.append(box);
      }
      form.append(fs);
    }
  }
  function setAnswer(id, value) {
    answers[id] = value;
    refreshAssumptions();
  }

  let assumeTimer = null;
  function refreshAssumptions() {
    if (!engineReady) return;
    clearTimeout(assumeTimer);
    assumeTimer = setTimeout(async () => {
      const out = await OtwinHome.call("assumptions", { answers });
      const box = $("assume");
      box.replaceChildren(
        el("h3", { text: "What your twin starts from" }),
        el("ul", {}, out.sentences.map((s) => el("li", { text: s }))),
      );
    }, 150);
  }

  /* ------------------------------------------------------------ step 2 */
  const drop = $("drop");
  for (const ev of ["dragenter", "dragover"]) {
    drop.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.add("over");
    });
  }
  for (const ev of ["dragleave", "drop"]) {
    drop.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.remove("over");
    });
  }
  drop.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
  $("files").addEventListener("change", (e) => {
    addFiles(e.target.files);
    e.target.value = "";
  });
  // the whole page accepts a drop, so a near miss does not open the file
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());

  async function addFiles(list) {
    // FileList is live: the input is cleared and a drop's list expires once the
    // event ends, so take the files out before the first await.
    const items = [...list];
    for (const file of items) {
      const id = `f${++fileCounter}`;
      files.set(id, { id, name: file.name, status: "busy", message: "Reading …" });
      renderFiles();
      const bytes = new Uint8Array(await file.arrayBuffer());
      try {
        const out = await OtwinHome.call(
          "read_file",
          { file_id: id, name: file.name, timezone_name: timezoneOf() },
          bytes,
        );
        files.set(id, out);
      } catch (e) {
        files.set(id, { id, name: file.name, status: "error", message: e.message });
      }
      renderFiles();
    }
    refreshStatus();
  }

  function renderFiles() {
    const ul = $("filelist");
    ul.replaceChildren();
    for (const f of files.values()) {
      const tag = { ok: ["ok", "Read"], needs_mapping: ["map", "Needs your help"],
                    error: ["error", "Not read"], busy: ["busy", "Reading"] }[f.status];
      const li = el(
        "li",
        { class: "file", "data-file": f.name, "data-status": f.status },
        el(
          "div",
          { class: "file-head" },
          el("span", { class: "file-name", text: f.name }),
          el(
            "span",
            {},
            el("span", { class: `tag ${tag[0]}`, text: tag[1] }),
            el("button", {
              class: "remove", type: "button", title: "Remove", "aria-label": `Remove ${f.name}`,
              text: "×", onclick: () => removeFile(f.id),
            }),
          ),
        ),
        el("p", { class: "file-msg", text: f.message || "" }),
      );
      if (f.status === "needs_mapping" && f.mapping) li.append(mapper(f));
      ul.append(li);
    }
  }

  async function removeFile(id) {
    files.delete(id);
    renderFiles();
    if (engineReady) await OtwinHome.call("remove_file", { file_id: id });
    refreshStatus();
  }

  function mapper(f) {
    const m = f.mapping;
    const g = Object.assign({}, m.guess, f.choice || {});
    const select = (name, options, value) => {
      const s = el("select", { name });
      for (const [v, label] of options) s.append(el("option", { value: v, selected: v === value }, label));
      return s;
    };
    const cols = m.headers.map((h) => [h, h]);
    const timeSel = select("time", cols, g.time);
    const valueSel = select("value", cols, g.value);
    const qSel = select("quantity", m.quantities.map((q) => [q.value, q.label]), g.quantity);
    const unitsFor = (q) => (m.quantities.find((x) => x.value === q) || { units: [] }).units;
    const unitSel = select("unit", unitsFor(g.quantity).map((u) => [u, u]), g.unit);
    const counter = el("input", { type: "checkbox", name: "cumulative", checked: !!g.cumulative });
    const counterRow = el("label", { class: "check" }, counter,
      "The values are a meter reading that only goes up");
    const energyLike = (q) => !q.endsWith("temperature");
    counterRow.hidden = !energyLike(g.quantity);
    qSel.addEventListener("change", () => {
      unitSel.replaceChildren(...unitsFor(qSel.value).map((u) => el("option", { value: u }, u)));
      counterRow.hidden = !energyLike(qSel.value);
    });
    const table = el("table", {},
      el("tr", {}, m.headers.map((h) => el("th", { text: h }))),
      m.preview.map((row) => el("tr", {}, row.map((c) => el("td", { text: c })))));
    const err = el("p", { class: "error", text: f.error || "" });
    const go = el("button", {
      type: "button", class: "primary small", text: "Read with these columns",
      onclick: async () => {
        const mapping = {
          time: timeSel.value, value: valueSel.value, quantity: qSel.value, unit: unitSel.value,
          cumulative: counter.checked, label: "start",
        };
        f.choice = mapping;
        go.disabled = true;
        const out = await OtwinHome.call("map_file", { file_id: f.id, mapping,
                                                        timezone_name: timezoneOf() });
        files.set(f.id, Object.assign({ mapping: f.mapping, choice: mapping }, out));
        renderFiles();
        refreshStatus();
      },
    });
    return el("div", { class: "mapper" },
      el("div", { class: "preview" }, table),
      el("label", {}, "Which column has the date and time?", timeSel),
      el("label", {}, "Which column has the values?", valueSel),
      el("label", {}, "What are they?", qSel),
      el("label", {}, "In what unit?", unitSel),
      counterRow, err, el("p", {}, go));
  }

  async function refreshStatus() {
    const box = $("status2");
    if (!engineReady) {
      box.replaceChildren(el("p", { class: "small", text: "Waiting for the engine …" }));
      return;
    }
    const st = await OtwinHome.call("data_status", { answers });
    box.replaceChildren(
      ...st.messages.map((m, i) =>
        el("p", { class: st.ready && i === 0 ? "ready" : "", text: m })),
    );
    if (st.weather_request) box.append(weatherOffer(st.weather_request));
    $("to3").disabled = !st.ready;
    if (st.ready) {
      $("period").textContent =
        `${st.messages[0].replace(/^Ready: /, "")} The twin will adjust itself until it ` +
        "uses electricity the way your home did.";
    }
  }

  function weatherOffer(req) {
    const status = el("p", { class: "small" });
    const button = el("button", {
      type: "button", class: "small",
      text: `Get the weather for ${req.province}, ${req.first} to ${req.last}`,
      onclick: async () => {
        button.disabled = true;
        status.textContent = "Asking Open-Meteo …";
        try {
          const r = await fetch(req.url);
          if (!r.ok) throw new Error(`Open-Meteo answered ${r.status}`);
          const bytes = new Uint8Array(await r.arrayBuffer());
          const id = `f${++fileCounter}`;
          const out = await OtwinHome.call(
            "read_file",
            { file_id: id, name: `open_meteo_${req.province}.json`, timezone_name: timezoneOf() },
            bytes,
          );
          files.set(id, out);
          renderFiles();
          refreshStatus();
        } catch (e) {
          status.textContent =
            `Could not reach Open-Meteo (${e.message}). You can download the weather ` +
            "yourself and drop the file above.";
          button.disabled = false;
        }
      },
    });
    return el("div", { class: "weather" },
      el("p", { text: "This sends only your province’s location and the dates to Open-Meteo, " +
                      "never your consumption or your files." }),
      button, status);
  }

  $("samples").addEventListener("click", async () => {
    if (!engineReady) {
      $("status2").replaceChildren(el("p", { text: "The engine is still starting; one moment …" }));
      await OtwinHome.start();
    }
    const out = await OtwinHome.call("load_samples", {});
    Object.assign(answers, out.answers);
    renderSurvey();
    refreshAssumptions();
    for (const f of out.files) files.set(f.id, f);
    renderFiles();
    refreshStatus();
  });

  /* ------------------------------------------------------------ step 3 */
  $("calibrate").addEventListener("click", async () => {
    const button = $("calibrate");
    const progress = $("progress");
    const report = $("report");
    button.disabled = true;
    report.replaceChildren();
    progress.hidden = false;
    const t0 = performance.now();
    const tick = () => {
      const s = Math.round((performance.now() - t0) / 1000);
      progress.textContent = `Fitting your month of hours … ${s} s (usually 20–40 s)`;
    };
    tick();
    const timer = setInterval(tick, 500);
    try {
      const out = await OtwinHome.call("calibrate_home", { answers });
      renderReport(out);
    } catch (e) {
      report.replaceChildren(el("p", { class: "error", text: `Something went wrong: ${e.message}` }));
    } finally {
      clearInterval(timer);
      progress.hidden = true;
      button.disabled = false;
      button.textContent = "Calibrate again";
    }
  });

  function renderReport(r) {
    const report = $("report");
    if (!r.ok) {
      report.replaceChildren(el("p", { class: "headline", text: r.message }));
      return;
    }
    const cls = (v) => (v === "good" ? "good" : v === "usable" ? "usable" : "lack");
    report.replaceChildren(
      el("span", { class: `verdict ${cls(r.verdict)}`, id: "verdict", text: r.verdict }),
      el("p", { class: "headline", text: r.headline }),
      ...r.notes.map((n) => el("p", { class: "note", text: n })),
      el("ul", { class: "findings" }, r.findings.map((f) =>
        el("li", { class: "finding" },
          el("div", { class: "finding-head" },
            el("span", { class: "finding-label", text: f.label }),
            el("span", { class: `chip ${cls(f.verdict)}`, text: f.verdict })),
          el("p", { text: `${withoutLabel(f.sentence, f.label)}.` }),
          f.reason ? el("p", { class: "reason", text: f.reason }) : null))),
      chart(r.daily),
      el("p", { class: "small", text:
        `Fitted on ${r.period}. A typical hour is within ${Math.round(100 * r.hourly_error)} % ` +
        `of your meter. Took ${r.seconds} s, all of it in this browser.` }),
    );
  }

  function withoutLabel(sentence, label) {
    // "How fast your home loses heat: 185 W ..." under that very heading
    if (!sentence.startsWith(`${label}: `)) return sentence;
    const rest = sentence.slice(label.length + 2);
    return rest.charAt(0).toUpperCase() + rest.slice(1);
  }

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const shortDay = (iso) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;

  function chart(daily) {
    const W = 720, H = 210, pad = 28, top = 34;
    const max = Math.max(...daily.map((d) => Math.max(d.measured, d.twin)), 1);
    const bw = (W - 2 * pad) / daily.length;
    const y = (v) => H - pad - (v / max) * (H - pad - top);
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Electricity per day: your meter and the twin");
    const add = (tag, attrs) => {
      const n = document.createElementNS(NS, tag);
      for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
      svg.append(n);
      return n;
    };
    daily.forEach((d, i) => add("rect", {
      x: pad + i * bw + 1, y: y(d.measured), width: Math.max(bw - 2, 1),
      height: H - pad - y(d.measured), fill: "#d2d2d7", rx: 2,
    }));
    add("polyline", {
      points: daily.map((d, i) => `${pad + (i + 0.5) * bw},${y(d.twin)}`).join(" "),
      fill: "none", stroke: "#0a66c2", "stroke-width": 2.5, "stroke-linejoin": "round",
    });
    add("line", { x1: pad, x2: W - pad, y1: H - pad, y2: H - pad, stroke: "#6e6e73" });
    const label = (text, x, yy, anchor) => {
      const t = add("text", { x, y: yy, "font-size": 12, fill: "#6e6e73", "text-anchor": anchor });
      t.textContent = text;
    };
    add("line", { x1: pad, x2: W - pad, y1: top, y2: top, stroke: "#e5e5ea", "stroke-dasharray": "3 4" });
    label(`${max.toFixed(0)} kWh a day`, pad, top - 8, "start");
    label(shortDay(daily[0].day), pad, H - 8, "start");
    label(shortDay(daily[daily.length - 1].day), W - pad, H - 8, "end");
    return el("div", { class: "chart" },
      el("p", { class: "finding-label", text: "Electricity per day" }),
      svg,
      el("div", { class: "legend" },
        el("span", {}, el("i", { style: "background:#d2d2d7" }), "your meter"),
        el("span", {}, el("i", { style: "background:#0a66c2" }), "your twin")));
  }

  /* ------------------------------------------------------------ start */
  for (const q of Q.questions) {
    answers[q.id] = Array.isArray(q.default) ? [...q.default] : q.default;
  }
  renderSurvey();
  showStep(1, false);
  window.OtwinWizard = { answers, files }; // for the end-to-end checks
})();
