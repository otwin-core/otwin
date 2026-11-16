/* One home, its data and its answer: the logic behind a section.
 *
 * "Your home" and "Demo" each own one of these. It keeps the engine's
 * session pointed at its own workspace, reads what is dropped on it, and
 * analyses the home again by itself whenever something changes. The last
 * answer stays on screen while a new one is worked out.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import * as engine from "./engine";

const DEBOUNCE_MS = 500;
const paint = () => new Promise((r) => setTimeout(r, 40)); // let the page draw first

export function useHome({ id, slice, patch, demoKey, engineReady, active, lang }) {
  const [summaries, setSummaries] = useState(() => new Map());
  const [task, setTask] = useState(""); // "", "preparing", "analyse", "trust"
  const [seconds, setSeconds] = useState(0);
  const [failure, setFailure] = useState("");
  const [weatherBusy, setWeatherBusy] = useState(false);
  const [weatherMessage, setWeatherMessage] = useState("");
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
  const runTrust = useCallback(() => engine.serial(async () => {
    if (busy.current) return;
    busy.current = true;
    setTask("trust");
    setSeconds(0);
    await paint();
    try {
      await ensure();
      const trust = await engine.call("trust_test", { answers: sliceRef.current.answers });
      const report = sliceRef.current.report;
      if (report) patch({ report: { ...report, trust } });
    } catch (e) {
      setFailure(e.message);
    } finally {
      busy.current = false;
      setTask("");
    }
  }), [ensure, patch]);

  const analyse = useCallback(
    (force = false) =>
      engine.serial(async () => {
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
      patch({ report: out, previous: sliceRef.current.report });
      if (out.example) {
        // the demo was simulated again: its files changed
        const files = await engine.call("files", { timezone_name: timezone() });
        setSummaries(new Map(files.files.map((f) => [f.id, f])));
        const cards = await engine.call("cards", { answers });
        patch({ cards });
      }
    } else {
      setFailure(out.message);
      patch({ report: null });
    }
    if (version.current !== at) {
      analyse(); // something changed while we were fitting
      return;
    }
    // where the engine has its own thread, test it on a hidden month too
    if (out.ok && (sliceRef.current.cards?.periods?.length || 0) >= 2 && engine.engineMode() === "worker") {
      runTrust();
    }
      }),
    [engineReady, ensure, patch, runTrust, timezone],
  );

  /* Analyse again in a moment (the data was marked changed by the caller). */
  const schedule = useCallback(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => analyse(), DEBOUNCE_MS);
  }, [analyse]);

  /* The data or the answers changed: say so before scheduling a run, so a
     run that starts in between is not repeated for nothing. */
  const changed = useCallback(() => {
    version.current += 1;
  }, []);

  /* ---------------------------------------------------------- the data */
  const addFiles = useCallback(
    (list) => {
      // Read the bytes now, not in the job: a FileList is live and the input
      // is cleared as soon as this returns, so by the time the engine is free
      // the files would be gone.
      const items = [...list].map((file) => ({
        id: `f${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
        name: file.name,
        bytes: file.arrayBuffer(),
      }));
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
        if (out.status === "needs_mapping" && out.mapping?.confident) {
          // a thermometer's or a weather station's log: read it with the guess
          mapping = out.mapping.guess;
          const mapped = await engine.call("map_file", { file_id: id_, mapping, timezone_name: tz });
          if (mapped.status === "ok") out = mapped;
          else mapping = null;
        }
        setSummaries((m) => new Map(m).set(id_, out));
        added.push({ id: id_, name: file.name, bytes: keep, mapping });
      }
      changed();
      patch({ files: [...sliceRef.current.files, ...added] });
      await refresh();
      schedule();
      });
    },
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
      patch({
        files: sliceRef.current.files.filter((f) => f.id !== fileId),
        bills: sliceRef.current.bills.filter((b) => b.id !== fileId),
      });
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
        patch({ bills: [...sliceRef.current.bills, { id: id_, kind, bill }] });
        await refresh();
        schedule();
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
    // one job: the engine's session must not be swapped under a fit
    engine.serial(async () => {
      setTask("preparing");
      try {
        const out = await ensure();
        await refresh(out?.answers);
        if (!sliceRef.current.report) {
          changed(); // there is no report yet: make the first one
          schedule();
        } else {
          analysedAt.current = version.current; // the report on screen is current
        }
      } finally {
        setTask("");
      }
    });
  }, [active, engineReady, id, demoKey, slice.answers, ensure, refresh, schedule]);

  /* the language changed: every sentence comes from the engine again */
  useEffect(() => {
    if (!active || !engineReady || !slice.answers) return;
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
    removeFile,
    addBill,
    mapFile,
    fetchWeather,
    setAnswers,
    analyse,
    runTrust,
    refresh,
  };
}
