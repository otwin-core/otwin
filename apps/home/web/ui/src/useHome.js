/* One home, its data and its answer: the logic behind a section.
 *
 * "Your home" and "Demo" each own one of these. It keeps the engine's
 * session pointed at its own workspace, reads what is dropped on it, and
 * analyses the home again by itself whenever something changes. The last
 * answer stays on screen while a new one is worked out.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import * as engine from "./engine";
import { isDocument } from "./ocr/engine";

const DEBOUNCE_MS = 500;
const paint = () => new Promise((r) => setTimeout(r, 40)); // let the page draw first

export function useHome({ id, slice, patch, demoKey, engineReady, active, lang }) {
  const [summaries, setSummaries] = useState(() => new Map());
  const [task, setTask] = useState(""); // "", "preparing", "analyse"
  const [seconds, setSeconds] = useState(0);
  const [failure, setFailure] = useState("");
  const [weatherBusy, setWeatherBusy] = useState(false);
  const [weatherMessage, setWeatherMessage] = useState("");
  //  Documents (a PDF, a photo of a bill) are read in the page, not by the
  //  engine: they wait here, in order, until the householder has checked
  //  what was read and added it as a bill. {id, name, bytes, state, pages, result}
  const [docs, setDocs] = useState([]);
  const busy = useRef(false);
  //  Every change to the data or the answers bumps `version`; a report is
  //  made from one version. The engine runs on this thread when the page is
  //  opened from disk, so timers cannot be relied on to cancel each other:
  //  what counts is whether anything actually changed since the last report.
  const version = useRef(0);
  const analysedAt = useRef(-1);
  const timer = useRef(null);
  const sliceRef = useRef(slice);
  sliceRef.current = slice;

  const timezone = useCallback(() => {
    const answers = sliceRef.current.answers;
    const list = (window.OTWIN_QUESTIONS?.en || window.OTWIN_QUESTIONS)?.provinces || [];
    const p = list.find((x) => x.value === answers?.province);
    return p ? p.timezone : "Europe/Madrid";
  }, []);

  const spec = useCallback(
    () =>
      demoKey
        ? { demo: demoKey }
        : { files: sliceRef.current.files, bills: sliceRef.current.bills, timezone: timezone() },
    [demoKey, timezone],
  );

  /* Point the engine's session at this workspace, if it is not already. */
  const ensure = useCallback(async () => {
    const out = await engine.useWorkspace(id, spec());
    if (out) {
      setSummaries(out.summaries);
      if (out.answers && !sliceRef.current.answers) patch({ answers: out.answers });
    }
    return out;
  }, [id, spec, patch]);

  /* The header, the first estimate and the cards, from the answers. */
  const refresh = useCallback(async (override) => {
    const answers = override || sliceRef.current.answers;
    if (!engineReady || !answers) return undefined;
    await ensure();
    const [home, cards] = await Promise.all([
      engine.call("home", { answers }),
      engine.call("cards", { answers }),
    ]);
    patch({ home, cards });
    if (sliceRef.current.weatherOk) {
      const w = cards.cards?.find((c) => c.kind === "weather");
      if (w?.status === "needs_ok") fetchWeather(w.request);
    }
    return cards;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engineReady, ensure, patch]);

  /* What a home with these answers looks like, for the questions screen. */
  const fetchHome = useCallback(
    async (answers) => {
      await ensure();
      return engine.call("home", { answers });
    },
    [ensure],
  );

  /* ---------------------------------------------------------- analysis */
  //  The fit itself, as a plain job: `analyse` queues it, `build` runs it
  //  inside its own job (a job waiting on another job would wait forever).
  const runAnalyse = useCallback(
    async (force = false) => {
    clearTimeout(timer.current);
    timer.current = null;
    if (busy.current) return; // the run under way will catch up at its end
    const answers = sliceRef.current.answers;
    const at = version.current;
    if (!engineReady || !answers) return;
    if (!force && analysedAt.current === at) return; // nothing has changed
    busy.current = true;
    setTask("analyse");
    setSeconds(0);
    await paint();
    let out;
    try {
      await ensure();
      const cards = await engine.call("cards", { answers });
      patch({ cards });
      if (!cards.ready) {
        patch({ report: null });
        busy.current = false;
        setTask("");
        return;
      }
      out = await engine.call("analyse", { answers });
    } catch (e) {
      out = { ok: false, message: e.message };
    }
    busy.current = false;
    analysedAt.current = at;
    setTask("");
    if (out.ok) {
      setFailure("");
      patch({ report: out, previous: sliceRef.current.report, stale: false, simulation: null });
      if (out.example) {
        // the demo was simulated again: its files changed
        const files = await engine.call("files", { timezone_name: timezone() });
        setSummaries(new Map(files.files.map((f) => [f.id, f])));
        const cards = await engine.call("cards", { answers });
        patch({ cards });
      }
    } else {
      setFailure(out.message);
      patch({ report: null, stale: false, simulation: null });
    }
    if (version.current !== at) {
      if (demoKey) analyse(); // something changed while we were fitting
      else patch({ stale: true });
    }
    },
    [engineReady, ensure, patch, timezone, demoKey],
  );

  const analyse = useCallback((force = false) => engine.serial(() => runAnalyse(force)), [runAnalyse]);

  /* The data or the answers changed. A demo is fitted again by itself (its
     files were just simulated anew); the householder's home waits for
     "Build / Update my digital home": building a model is their decision,
     and they may still be adding files. Meanwhile the home is marked
     `stale`, so the page can say the files changed since the last fit. */
  const schedule = useCallback(() => {
    clearTimeout(timer.current);
    if (demoKey) {
      timer.current = setTimeout(() => analyse(), DEBOUNCE_MS);
      return;
    }
    patch({ stale: true });
  }, [analyse, demoKey, patch]);

  /* The data or the answers changed: say so before scheduling a run, so a
     run that starts in between is not repeated for nothing. A demo shown
     from its baked answer is from now on a home like any other: fitted
     here, in the browser. */
  const changed = useCallback(() => {
    version.current += 1;
    if (sliceRef.current.baked) patch({ baked: false });
    // a home that started from a demo: its files or answers are no longer the demo's
    if (sliceRef.current.demo && !sliceRef.current.demoTouched) patch({ demoTouched: true });
  }, [patch]);

  /* A home straight from a demo is built at once from the fit baked at build
     time (demos.js), in this language; the engine is told the fitted values
     so the simulation can run on them. Once the home is touched, "build"
     fits for real like any other home. */
  const bakedFor = (lang_) => (sliceRef.current.demo && !sliceRef.current.demoTouched ? window.OTWIN_DEMOS?.[sliceRef.current.demo]?.[lang_] || null : null);
  const build = useCallback(
    () =>
      engine.serial(async () => {
        const baked = bakedFor(lang);
        if (!baked) {
          await runAnalyse(true);
          return;
        }
        setTask("analyse");
        await paint();
        try {
          await ensure();
          await engine.call("adopt_fit", { answers: sliceRef.current.answers, fit: window.OTWIN_DEMOS[sliceRef.current.demo].fit || {} });
          patch({ home: baked.home, cards: baked.cards, report: baked.report, stale: false });
          analysedAt.current = version.current;
        } finally {
          setTask("");
        }
      }),
    [runAnalyse, ensure, lang, patch],
  );

  /* the language changed on a demo home built from the baked fit: its baked words in the new language */
  useEffect(() => {
    const baked = bakedFor(lang);
    if (baked && sliceRef.current.report) patch({ home: baked.home, cards: baked.cards, report: baked.report });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang]);

  /* The next twelve months on the fitted model, with changes and prices. */
  const forecast = useCallback(
    (changes, prices) =>
      engine.serial(async () => {
        await ensure();
        try {
          return await engine.call("forecast", { answers: sliceRef.current.answers, changes: changes || {}, prices: prices || null });
        } catch (e) {
          return { ok: false, message: e.message };
        }
      }),
    [ensure],
  );
  const setSimulation = useCallback((simulation) => patch({ simulation }), [patch]);

  /* A demo's answer, worked out at build time (demos.js) in this language:
     its files as the engine describes them, its first estimate, its cards
     and its analysis. Shown at once, with no engine at all; the engine is
     only asked for something once the demo is edited or given a file. */
  const baked =
    demoKey && slice.baked ? window.OTWIN_DEMOS?.[demoKey]?.[lang] || null : null;
  useEffect(() => {
    if (!baked) return;
    setSummaries(new Map(baked.files.map((f) => [f.id, f])));
    patch({ home: baked.home, cards: baked.cards, report: baked.report });
    analysedAt.current = version.current; // the answer on screen is current
  }, [baked, patch]);

  /* ---------------------------------------------------------- the data */
  /* `kind` is what the householder said the files are ("gas", "electricity",
     "water", "thermometer", "weather"): kept with each file, and the hint
     the bill reader starts from. */
  const addFiles = useCallback(
    (list, kind = null) => {
      // Read the bytes now, not in the job: a FileList is live and the input
      // is cleared as soon as this returns, so by the time the engine is free
      // the files would be gone.
      const all = [...list].map((file) => ({
        id: `f${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
        name: file.name,
        bytes: file.arrayBuffer(),
      }));
      // a PDF or a photo is a bill to read in the page first
      const documents = all.filter((f) => isDocument(f.name));
      const items = all.filter((f) => !isDocument(f.name));
      if (documents.length) {
        Promise.all(documents.map(async (d) => ({ ...d, bytes: new Uint8Array(await d.bytes), state: "new", hint: kind }))).then((ds) =>
          setDocs((cur) => [...cur, ...ds]),
        );
      }
      if (!items.length) return undefined;
      return engine.serial(async () => {
      if (!sliceRef.current.answers) return;
      await ensure();
      const tz = timezone();
      const added = [];
      for (const file of items) {
        const id_ = file.id;
        // keep our own copy first: sending the bytes to the engine's worker
        // transfers (and empties) the buffer they are a view on
        const buffer = await file.bytes;
        const keep = buffer.slice(0);
        const bytes = new Uint8Array(buffer);
        setSummaries((m) => new Map(m).set(id_, { id: id_, name: file.name, status: "busy" }));
        await paint();
        let out = await engine.call(
          "read_file",
          { file_id: id_, name: file.name, timezone_name: tz },
          bytes,
        );
        let mapping = null;
        if (out.status === "needs_mapping" && (out.mapping?.confident || (kind === "thermometer" && out.mapping))) {
          // a thermometer's or a weather station's log: read it with the guess
          mapping = out.mapping.guess;
          const mapped = await engine.call("map_file", { file_id: id_, mapping, timezone_name: tz });
          if (mapped.status === "ok") out = mapped;
          else mapping = null;
        }
        setSummaries((m) => new Map(m).set(id_, out));
        added.push({ id: id_, name: file.name, bytes: keep, mapping, kind, enabled: true });
      }
      changed();
      patch((h) => ({ files: [...h.files, ...added] }));
      await refresh();
      schedule();
      });
    },
    [changed, ensure, patch, refresh, schedule, timezone],
  );

  /* A file in or out of the calibration: out, the engine forgets it; in
     again, it is read again. The page keeps it either way. */
  const toggleFile = useCallback(
    (fileId) =>
      engine.serial(async () => {
        const file = sliceRef.current.files.find((f) => f.id === fileId);
        if (!file) return;
        await ensure();
        const enabled = file.enabled === false;
        if (enabled) {
          const tz = timezone();
          let out = await engine.call("read_file", { file_id: fileId, name: file.name, timezone_name: tz }, new Uint8Array(file.bytes.slice(0)));
          if (out.status === "needs_mapping" && (file.mapping || out.mapping?.confident || file.kind === "thermometer")) out = await engine.call("map_file", { file_id: fileId, mapping: file.mapping || out.mapping.guess, timezone_name: tz });
          setSummaries((m) => new Map(m).set(fileId, out));
        } else {
          await engine.call("remove_file", { file_id: fileId });
        }
        changed();
        patch((h) => ({ files: h.files.map((f) => (f.id === fileId ? { ...f, enabled } : f)) }));
        await refresh();
        schedule();
      }),
    [changed, ensure, patch, refresh, schedule, timezone],
  );

  const removeFile = useCallback(
    async (fileId) => {
      await ensure();
      await engine.call("remove_file", { file_id: fileId });
      setSummaries((m) => {
        const next = new Map(m);
        next.delete(fileId);
        return next;
      });
      changed();
      patch((h) => ({
        files: h.files.filter((f) => f.id !== fileId),
        bills: h.bills.filter((b) => b.id !== fileId),
      }));
      await refresh();
      schedule();
    },
    [changed, ensure, patch, refresh, schedule],
  );

  const addBill = useCallback(
    async (kind, bill) => {
      await ensure();
      const id_ = `b${Date.now().toString(36)}`;
      const out = await engine.call("add_bill", {
        file_id: id_,
        kind,
        bill,
        timezone_name: timezone(),
      });
      if (out.status === "ok") {
        changed();
        setSummaries((m) => new Map(m).set(id_, out));
        patch((h) => ({ bills: [...h.bills, { id: id_, kind, bill, enabled: true }] }));
        // the bill is in: answer now, so the page can put the form away; the
        // header and the fit catch up in the background
        refresh().then(() => schedule());
      } else {
        await engine.call("remove_file", { file_id: id_ });
      }
      return out;
    },
    [changed, ensure, patch, refresh, schedule, timezone],
  );

  const mapFile = useCallback(
    async (fileId, mapping) => {
      await ensure();
      const out = await engine.call("map_file", {
        file_id: fileId,
        mapping,
        timezone_name: timezone(),
      });
      setSummaries((m) => new Map(m).set(fileId, { ...m.get(fileId), ...out, choice: mapping }));
      if (out.status === "ok") {
        changed();
        patch({
          files: sliceRef.current.files.map((f) => (f.id === fileId ? { ...f, mapping } : f)),
        });
        await refresh();
        schedule();
      }
      return out;
    },
    [changed, ensure, patch, refresh, schedule, timezone],
  );

  const fetchWeather = useCallback(
    async (request) => {
      if (!request || weatherBusy) return;
      setWeatherBusy(true);
      setWeatherMessage("fetching");
      try {
        const r = await fetch(request.url);
        if (!r.ok) throw new Error(`Open-Meteo ${r.status}`);
        const buffer = await r.arrayBuffer();
        const keep = buffer.slice(0); // the call below may transfer the bytes
        const bytes = new Uint8Array(buffer);
        const name = `open_meteo_${request.first}_${request.last}.json`;
        const id_ = `w${Date.now().toString(36)}`;
        await ensure();
        const out = await engine.call(
          "read_file",
          { file_id: id_, name, timezone_name: timezone() },
          bytes,
        );
        changed();
        setSummaries((m) => new Map(m).set(id_, out));
        patch({
          weatherOk: true,
          files: [...sliceRef.current.files, { id: id_, name, bytes: keep, mapping: null }],
        });
        setWeatherMessage("");
        await refresh();
        schedule();
      } catch (e) {
        setWeatherMessage(e.message);
      } finally {
        setWeatherBusy(false);
      }
    },
    [changed, ensure, patch, refresh, schedule, timezone, weatherBusy],
  );

  const updateDoc = useCallback((id, part) => setDocs((cur) => cur.map((d) => (d.id === id ? { ...d, ...part } : d))), []);
  const dismissDoc = useCallback((id) => setDocs((cur) => cur.filter((d) => d.id !== id)), []);
  /* The fields of a bill, from the words read on its pages (the engine's reader). */
  const readInvoice = useCallback(
    async (pages, hint) => {
      await ensure();
      return engine.call("read_invoice", { pages, hint: hint || null });
    },
    [ensure],
  );

  const setAnswers = useCallback(
    async (answers) => {
      const different = JSON.stringify(answers) !== JSON.stringify(sliceRef.current.answers);
      patch({ answers, onboarded: true });
      if (!different) return;
      changed();
      await refresh();
      schedule();
    },
    [changed, patch, refresh, schedule],
  );

  /* ---------------------------------------------------------- the clock */
  useEffect(() => {
    if (!task) return undefined;
    const started = performance.now();
    const tick = setInterval(() => setSeconds(Math.round((performance.now() - started) / 1000)), 1000);
    return () => clearInterval(tick);
  }, [task]);

  /* when this section is opened, bring the engine to it */
  const prepared = useRef(false);
  useEffect(() => {
    // a demo brings its own answers with it; a home of one's own is described first
    if (!active || !engineReady || (!demoKey && !slice.answers)) return;
    const key = id + (demoKey || "");
    if (prepared.current === key) return;
    prepared.current = key;
    if (sliceRef.current.baked) return; // its answer is baked: nothing to prepare
    // one job: the engine's session must not be swapped under a fit
    engine.serial(async () => {
      setTask("preparing");
      try {
        const out = await ensure();
        await refresh(out?.answers);
        if (!sliceRef.current.report && demoKey) {
          changed(); // a demo with no report yet: make the first one
          schedule();
        } else {
          analysedAt.current = version.current; // the report on screen is current
        }
      } finally {
        setTask("");
      }
    });
  }, [active, engineReady, id, demoKey, slice.answers, ensure, refresh, schedule]);

  /* the language changed: every sentence comes from the engine again (a
     baked demo has both languages baked: see above) */
  useEffect(() => {
    if (!active || !engineReady || !slice.answers || slice.baked) return;
    let gone = false;
    engine.serial(async () => {
      await ensure();
      const files = await engine.call("files", { timezone_name: timezone() });
      if (gone) return;
      setSummaries(new Map(files.files.map((f) => [f.id, f])));
      const [home, cards] = await Promise.all([
        engine.call("home", { answers: sliceRef.current.answers }),
        engine.call("cards", { answers: sliceRef.current.answers }),
      ]);
      const patched = { home, cards };
      if (sliceRef.current.report) {
        const again = await engine.call("report");
        if (again.ok) patched.report = { ...again, trust: again.trust || sliceRef.current.report.trust };
      }
      if (!gone) patch(patched);
    });
    return () => {
      gone = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang]);

  return {
    fetchHome,
    summaries,
    task,
    seconds,
    failure,
    weatherBusy,
    weatherMessage,
    addFiles,
    toggleFile,
    removeFile,
    addBill,
    mapFile,
    fetchWeather,
    docs,
    updateDoc,
    dismissDoc,
    readInvoice,
    setAnswers,
    analyse,
    build,
    forecast,
    setSimulation,
    refresh,
  };
}
