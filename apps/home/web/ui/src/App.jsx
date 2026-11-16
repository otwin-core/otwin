/* Otwin Home: four sections, each on its own.
 *
 * "Your home" and "Demo" each own a home, its files and its results, kept
 * apart in this browser and in the engine's session. "Simulation" is where
 * predictions will go. "Help" says what this is and what happens to your
 * data. The engine (web/py) is not touched by any of it.
 */
import * as Tabs from "@radix-ui/react-tabs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import * as engine from "./engine";
import { LangContext, translate, useT } from "./i18n";
import { Confirm } from "./parts/bits";
import { Demo } from "./parts/Demo";
import { Help } from "./parts/Help";
import { Simulation } from "./parts/Simulation";
import { YourHome } from "./parts/YourHome";
import { clearAll, emptyState, emptyWorkspace, load, save } from "./store";
import { useHome } from "./useHome";

const SECTIONS = ["home", "demo", "simulation", "help"];

export function App() {
  const [state, setState] = useState(null); // null until this browser is read
  const [engineReady, setEngineReady] = useState(false);
  const [engineText, setEngineText] = useState("");
  const [engineState, setEngineState] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef(null);
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

  /* ------------------------------------------------------- the sections */
  const patchOwn = useCallback(
    (part) => setState((s) => ({ ...s, own: { ...s.own, ...part } })),
    [],
  );
  const patchDemo = useCallback(
    (part) => setState((s) => ({ ...s, demo: { ...s.demo, ...part } })),
    [],
  );
  const tab = state?.tab || "home";

  const questions = useMemo(() => {
    const all = window.OTWIN_QUESTIONS || {};
    return all[lang] || all.en || all;
  }, [lang]);

  const own = useHome({
    id: "own",
    slice: state?.own || emptyWorkspace(),
    patch: patchOwn,
    engineReady,
    active: tab === "home",
    lang,
  });
  const demo = useHome({
    id: `demo:${state?.demo?.key || "none"}`,
    slice: state?.demo || emptyWorkspace(),
    patch: patchDemo,
    demoKey: state?.demo?.key || null,
    engineReady,
    active: tab === "demo",
    lang,
  });
  const active = tab === "demo" ? demo : own;

  /* files dropped anywhere land in the section being looked at */
  useEffect(() => {
    const onOver = (e) => e.preventDefault();
    const onEnter = (e) => {
      e.preventDefault();
      if (tab === "home" || tab === "demo") setDragging(true);
    };
    const onLeave = (e) => {
      if (e.relatedTarget === null) setDragging(false);
    };
    const onDrop = (e) => {
      e.preventDefault();
      setDragging(false);
      if (tab === "home" || tab === "demo") active.addFiles(e.dataTransfer.files);
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
  }, [tab, active]);

  const forgetEverything = async () => {
    setConfirming(false);
    if (engineReady) await engine.call("forget");
    engine.invalidate();
    await clearAll();
    setState({ ...emptyState(), lang });
  };

  if (!state) return null; // one frame, while this browser is read

  const provinceLabel =
    questions.provinces?.find((p) => p.value === (tab === "demo" ? state.demo : state.own).answers?.province)
      ?.label || "";

  return (
    <LangContext.Provider value={lang}>
      <Shell
        state={state}
        setState={setState}
        engineText={engineText}
        engineState={engineState}
        tab={tab}
        onTab={(next) => setState((s) => ({ ...s, tab: next }))}
        onForget={() => setConfirming(true)}
      >
        <Tabs.Content value="home">
          <YourHome
            slice={state.own}
            control={own}
            questions={questions.questions || []}
            province={provinceLabel}
            onPick={() => fileInput.current?.click()}
            onDemo={() => setState((s) => ({ ...s, tab: "demo" }))}
            fileInput={<FilePicker inputRef={fileInput} onFiles={own.addFiles} />}
          />
        </Tabs.Content>
        <Tabs.Content value="demo">
          <Demo
            slice={state.demo}
            control={demo}
            questions={questions.questions || []}
            province={provinceLabel}
            onPick={() => fileInput.current?.click()}
            onChoose={(key) => {
              engine.invalidate();
              setState((s) => ({ ...s, demo: { ...emptyWorkspace(), key }, tab: "demo" }));
            }}
            onLeave={() => {
              engine.invalidate();
              setState((s) => ({ ...s, demo: { ...emptyWorkspace(), key: null } }));
            }}
            fileInput={<FilePicker inputRef={fileInput} onFiles={demo.addFiles} />}
          />
        </Tabs.Content>
        <Tabs.Content value="simulation">
          <Simulation hasHome={!!state.own.report} />
        </Tabs.Content>
        <Tabs.Content value="help">
          <Help onForget={() => setConfirming(true)} />
        </Tabs.Content>
      </Shell>
      {dragging ? <DropZone /> : null}
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

function Shell({ state, setState, engineText, engineState, tab, onTab, onForget, children }) {
  const { t } = useT();
  return (
    <Tabs.Root value={tab} onValueChange={onTab} className="shell">
      <header className="top">
        <div className="brand">
          <span className="mark" aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
          </span>
          {t("brand")}
        </div>
        <div className="top-right">
          <label className="lang">
            {t("language")}{" "}
            <select
              id="lang"
              aria-label="Language / Idioma"
              value={state.lang}
              onChange={(e) => setState((s) => ({ ...s, lang: e.target.value }))}
            >
              <option value="en">English</option>
              <option value="es">Español</option>
            </select>
          </label>
          <span className={`engine ${engineState}`} id="engine" aria-live="polite">
            <span className="dot" />
            {engineText || t("engine_starting")}
          </span>
        </div>
      </header>

      <Tabs.List className="sections" asChild>
        <nav className="sections" aria-label={t("nav_label")}>
          {SECTIONS.map((s) => (
            <Tabs.Trigger key={s} value={s} data-section={s}>
              {t(`nav_${s}`)}
            </Tabs.Trigger>
          ))}
        </nav>
      </Tabs.List>

      <main>{children}</main>

      <footer className="bottom">
        <p>
          <strong>{t("privacy_strong")}</strong> {t("privacy_rest")}
        </p>
        <div className="row">
          <span>{t("footer")}</span>
          <span>
            {typeof window.OTWIN_BUILD !== "undefined" ? t("built", window.OTWIN_BUILD) : ""}{" "}
            {t("saved_here")}{" "}
            <button type="button" className="plain" id="forget" onClick={onForget}>
              {t("forget_all")}
            </button>
          </span>
        </div>
      </footer>
    </Tabs.Root>
  );
}
