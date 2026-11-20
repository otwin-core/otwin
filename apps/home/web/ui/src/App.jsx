/* Otwin Home: a launch page and one door, "My home".
 *
 * "My home" holds the householder's homes, one or several, each with its
 * own files and results, on its pages: my home, your digital home (the
 * bills, and the model built from them), the simulation (only once the
 * model is built), help. A home may start from a demo home, whose bills are
 * its own. Everything about the page itself (language, the homes, what
 * this browser keeps) is behind the gear at the top left. The engine
 * (web/py) is not touched by any of it.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import * as engine from "./engine";
import { LangContext, translate, useT } from "./i18n";
import { Confirm, Settings } from "./parts/bits";
import { Main } from "./parts/Main";
import { YourHome } from "./parts/YourHome";
import { clearAll, emptyHome, emptyState, emptyWorkspace, load, save } from "./store";
import { useHome } from "./useHome";

const ROUTES = ["main", "home"];

export function App() {
  const [state, setState] = useState(null); // null until this browser is read
  const [engineReady, setEngineReady] = useState(false);
  const [engineText, setEngineText] = useState("");
  const [engineState, setEngineState] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [settings, setSettings] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef(null);
  const pickKind = useRef(null); // what the householder said the files about to be picked are
  const stateRef = useRef(state);
  stateRef.current = state;

  /* ------------------------------------------------------------ booting */
  useEffect(() => {
    (async () => {
      const saved = await load();
      setState(saved || emptyState());
    })();
  }, []);

  useEffect(() => {
    if (!state) return;
    save(state);
  }, [state]);

  const lang = state?.lang || "en";
  useEffect(() => {
    if (!state) return;
    document.documentElement.lang = lang;
    document.title = translate(lang, "title");
  }, [lang, state]);

  useEffect(() => {
    if (!state) return undefined;
    let gone = false;
    (async () => {
      try {
        const info = await engine.start((status) =>
          !gone && setEngineText(translate(stateRef.current?.lang || "en", "engine_loading", { status })),
        );
        if (gone) return;
        await engine.setLanguage(stateRef.current?.lang || "en");
        setEngineState("ready");
        setEngineReady(true);
        setEngineText(
          translate(stateRef.current?.lang || "en", info.mode === "worker" ? "engine_ready_worker" : "engine_ready_page"),
        );
      } catch (e) {
        if (gone) return;
        setEngineState("failed");
        setEngineText(translate(stateRef.current?.lang || "en", "engine_failed", { message: e.message }));
      }
    })();
    return () => {
      gone = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state !== null]);

  useEffect(() => {
    if (!engineReady) return;
    engine.setLanguage(lang);
    setEngineText(translate(lang, engine.engineMode() === "worker" ? "engine_ready_worker" : "engine_ready_page"));
  }, [lang, engineReady]);

  /* Nothing should fail quietly: a job that rejects says so. */
  useEffect(() => {
    const onRejection = (event) => {
      const why = event.reason?.message || String(event.reason);
      console.error(`Otwin Home: a job did not finish (${why})`);
    };
    window.addEventListener("unhandledrejection", onRejection);
    return () => window.removeEventListener("unhandledrejection", onRejection);
  }, []);

  /* ----------------------------------------------------------- the homes */
  const currentId = state?.current || null;
  const current = state?.homes.find((h) => h.id === currentId) || null;
  //  A patch is bound to one home by id: a fit that finishes after the
  //  householder moved to another home still lands where it belongs.
  //  `part` may be a function of the home as it is at that moment, so two
  //  changes landing together (removing several files) never undo each other.
  const patchHomeById = useCallback(
    (id) => (part) =>
      setState((s) => ({
        ...s,
        homes: s.homes.map((h) => (h.id === id ? { ...h, ...(typeof part === "function" ? part(h) : part) } : h)),
      })),
    [],
  );
  const patchOwn = useMemo(() => patchHomeById(currentId), [patchHomeById, currentId]);
  const patchDemo = useCallback(
    (part) => setState((s) => ({ ...s, demo: { ...s.demo, ...(typeof part === "function" ? part(s.demo) : part) } })),
    [],
  );
  /* A home that starts from a demo home: its answers and its own files,
     from the engine; built instantly from the baked fit until it is touched. */
  const addDemoHome = useCallback(async (key) => {
    const d = await engine.call("demo_home", { key });
    const files = d.files.map((f) => {
      const raw = atob(f.data);
      const bytes = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
      return { id: `f${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`, name: f.name, bytes: bytes.buffer, mapping: null, kind: f.kind, enabled: true };
    });
    const home = { ...emptyHome(d.name), answers: d.answers, onboarded: true, files, demo: key };
    engine.invalidate();
    setState((s) => ({ ...s, homes: [...s.homes.filter((h) => h.answers), home], current: home.id, page: "calibration" }));
    return home.id;
  }, []);
  const addHome = useCallback(() => {
    const described = stateRef.current.homes.filter((h) => h.answers).length;
    const home = emptyHome(
      translate(stateRef.current.lang, "home_default_name") + (described ? ` ${described + 1}` : ""),
    );
    engine.invalidate();
    setState((s) => ({ ...s, homes: [...s.homes, home], current: home.id }));
    return home.id;
  }, []);
  const pickHome = useCallback((id) => {
    engine.invalidate();
    setState((s) => ({ ...s, current: id }));
  }, []);
  const renameHome = useCallback(
    (id, name) => setState((s) => ({ ...s, homes: s.homes.map((h) => (h.id === id ? { ...h, name } : h)) })),
    [],
  );
  const removeHome = useCallback(async (id) => {
    engine.invalidate();
    setState((s) => {
      const homes = s.homes.filter((h) => h.id !== id);
      return { ...s, homes, current: s.current === id ? homes[0]?.id || null : s.current };
    });
  }, []);

  const route = ROUTES.includes(state?.route) ? state.route : "main";
  const page = state?.page || "home";
  const go = useCallback((next, nextPage) => setState((s) => ({ ...s, route: next, ...(nextPage ? { page: nextPage } : {}) })), []);

  const questions = useMemo(() => {
    const all = window.OTWIN_QUESTIONS || {};
    return all[lang] || all.en || all;
  }, [lang]);

  const own = useHome({
    id: `own:${currentId || "none"}`,
    slice: current || emptyWorkspace(),
    patch: patchOwn,
    engineReady,
    active: route === "home",
    lang,
  });
  /* files dropped anywhere land in the home being looked at */
  useEffect(() => {
    const onOver = (e) => e.preventDefault();
    const onEnter = (e) => {
      e.preventDefault();
      if (route === "home" && current?.onboarded) setDragging(true);
    };
    const onLeave = (e) => {
      if (e.relatedTarget === null) setDragging(false);
    };
    const onDrop = (e) => {
      e.preventDefault();
      setDragging(false);
      if (route === "home" && current?.onboarded) own.addFiles(e.dataTransfer.files);
    };
    window.addEventListener("dragover", onOver);
    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragover", onOver);
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("drop", onDrop);
    };
  }, [route, own, current]);

  const forgetEverything = async () => {
    setConfirming(false);
    setSettings(false);
    if (engineReady) await engine.call("forget");
    engine.invalidate();
    await clearAll();
    setState({ ...emptyState(), lang });
  };

  if (!state) return null; // one frame, while this browser is read

  const provinceOf = (answers) =>
    questions.provinces?.find((p) => p.value === answers?.province)?.label || "";

  return (
    <LangContext.Provider value={lang}>
      <Shell
        engineText={engineText}
        engineState={engineState}
        route={route}
        page={page}
        onMain={() => go("main")}
        onHome={() => go("home", "home")}
        onDigitalHome={() => go("home", "calibration")}
        onHelp={() => go("home", "help")}
        onSettings={() => setSettings(true)}
      >
        {route === "main" ? <Main homes={state.homes} onRoute={(r) => go(r, "home")} onHelp={() => go("home", "help")} /> : null}
        {route === "home" ? (
          <YourHome
            homes={state.homes}
            home={current}
            page={page}
            onPage={(p) => setState((s) => ({ ...s, page: p }))}
            control={own}
            questions={questions.questions || []}
            province={provinceOf(current?.answers)}
            onPick={(kind) => {
              pickKind.current = typeof kind === "string" ? kind : null;
              fileInput.current?.click();
            }}
            onStart={() => (current && !current.answers ? current.id : addHome())}
            onAddHome={addHome}
            onDemoHome={addDemoHome}
            engineReady={engineReady}
            onPickHome={pickHome}
            onRename={renameHome}
            onDiscard={removeHome}
            fileInput={<FilePicker inputRef={fileInput} onFiles={(files) => own.addFiles(files, pickKind.current)} />}
          />
        ) : null}
      </Shell>
      {dragging ? <DropZone /> : null}
      <Settings
        open={settings}
        onOpenChange={setSettings}
        lang={state.lang}
        onLang={(next) => setState((s) => ({ ...s, lang: next }))}
        homes={state.homes}
        current={currentId}
        onRename={renameHome}
        onRemove={removeHome}
        onForget={() => setConfirming(true)}
      />
      <Confirm
        open={confirming}
        onOpenChange={setConfirming}
        title={translate(lang, "forget_all")}
        text={translate(lang, "forget_confirm")}
        confirm={translate(lang, "forget_all")}
        cancel={translate(lang, "cancel")}
        onConfirm={forgetEverything}
      />
    </LangContext.Provider>
  );
}

function FilePicker({ inputRef, onFiles }) {
  return (
    <input
      id="files"
      ref={inputRef}
      type="file"
      multiple
      hidden
      onChange={(e) => {
        onFiles(e.target.files);
        e.target.value = "";
      }}
    />
  );
}

function DropZone() {
  const { t } = useT();
  return (
    <div className="dropzone" id="drop">
      <p>{t("drop_hint")}</p>
    </div>
  );
}

function Shell({ engineText, engineState, route, page, onMain, onHome, onDigitalHome, onHelp, onSettings, children }) {
  const { t } = useT();
  return (
    <div className="shell">
      <header className="top">
        <div className="brand">
          <button type="button" className="gear" id="settings" onClick={onSettings} aria-label={t("settings")} title={t("settings")}>
            <GearIcon />
          </button>
          <button type="button" className="plain brand-name" id="to-main" onClick={onMain} aria-label={t("back_main")}>
            <span className="mark" aria-hidden="true">
              <i />
              <i />
              <i />
              <i />
            </span>
            {t("brand")}
          </button>
        </div>
        <div className="top-right">
          <span className={`engine ${engineState}`} id="engine" aria-live="polite">
            <span className="dot" />
            {engineText || t("engine_starting")}
          </span>
        </div>
      </header>

      {route !== "main" ? (
        <nav className="crumbs" aria-label={t("nav_label")}>
          <button type="button" className="plain" id="back-main" onClick={onMain}>
            ← {t("back_main")}
          </button>
          <span className="sep">/</span>
          {route === "home" && page !== "home" ? (
            <>
              <button type="button" className="plain" id="back-home" onClick={onHome}>
                {t("route_home")}
              </button>
              <span className="sep">/</span>
              {page === "simulation" ? (
                <>
                  <button type="button" className="plain" id="back-digital" onClick={onDigitalHome}>
                    {t("page_calibration")}
                  </button>
                  <span className="sep">/</span>
                </>
              ) : null}
              <span className="here" data-page={page}>
                {t(`page_${page}`)}
              </span>
            </>
          ) : (
            <span className="here" data-route={route}>
              {t(`route_${route}`)}
            </span>
          )}
          {!(route === "home" && page === "help") ? (
            <button type="button" className="plain help-link" id="to-help" onClick={onHelp}>
              {t("page_help")}
            </button>
          ) : null}
        </nav>
      ) : null}

      <main>{children}</main>

      <footer className="bottom">
        <p>
          <strong>{t("privacy_strong")}</strong> {t("privacy_rest")}
        </p>
        <div className="row">
          <span>{t("footer")}</span>
          <span>{typeof window.OTWIN_BUILD !== "undefined" ? t("built", window.OTWIN_BUILD) : ""}</span>
        </div>
      </footer>
    </div>
  );
}

/* A gear, drawn here: eight teeth on a ring. */
function GearIcon() {
  const teeth = [];
  for (let i = 0; i < 8; i += 1) {
    teeth.push(<rect key={i} x="-2.6" y="-14" width="5.2" height="6" transform={`rotate(${i * 45})`} />);
  }
  return (
    <svg viewBox="-16 -16 32 32" width="26" height="26" aria-hidden="true">
      <g fill="currentColor">
        {teeth}
        <circle r="10" />
      </g>
      <circle r="4" fill="#ffffff" />
    </svg>
  );
}
