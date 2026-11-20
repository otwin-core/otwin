/* The launch page: one door, "My home", and help. Empty otherwise, on
 * purpose: what else goes here is still to be decided.
 */
import { useT } from "../i18n";

export function Main({ homes, onRoute, onHelp }) {
  const { t } = useT();
  const named = homes.filter((h) => h.answers);
  return (
    <div className="main">
      <h1>{t("main_title")}</h1>
      <p className="lead">{t("main_lead")}</p>
      <div className="doors">
        <button type="button" className="door" data-route="home" onClick={() => onRoute("home")}>
          <span className="band red" />
          <span className="inner">
            <span className="name">{t("route_home")}</span>
            <span className="small">{named.length ? named.map((h) => h.name).join(" · ") : t("main_home_desc")}</span>
          </span>
        </button>
      </div>
      <p className="small" style={{ marginTop: 28 }}>
        <button type="button" className="plain" id="main-help" onClick={onHelp}>
          {t("page_help")}
        </button>
      </p>
    </div>
  );
}
