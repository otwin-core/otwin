/* "Simulation": where the model will be asked about times it has not seen.
 * Empty on purpose: it is the next thing to be built.
 */
import { useT } from "../i18n";
import { Block } from "./bits";

export function Simulation({ hasHome }) {
  const { t } = useT();
  return (
    <div>
      <h1>{t("sim_title")}</h1>
      <p className="lead">{t("sim_lead")}</p>
      <p>
        <span className="soon">{t("sim_soon")}</span>
      </p>
      <Block colour="blue">
        <ul className="facts">
          <li>{t("sim_next_1")}</li>
          <li>{t("sim_next_2")}</li>
          <li>{t("sim_next_3")}</li>
        </ul>
        {hasHome ? null : <p className="small">{t("sim_needs")}</p>}
      </Block>
    </div>
  );
}
