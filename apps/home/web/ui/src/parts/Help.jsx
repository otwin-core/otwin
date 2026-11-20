/* "Help": what this is, what happens to your data, how to get your data,
 * and what the words mean.
 */
import * as Accordion from "@radix-ui/react-accordion";

import { useT } from "../i18n";

export function Help() {
  const { t } = useT();
  const sections = [
    ["what", "help_what", [t("help_what_text")]],
    ["privacy", "help_privacy", [t("help_privacy_text")]],
    ["data", "help_data", [t("help_data_elec"), t("help_data_gas"), t("help_data_thermo")]],
  ];
  return (
    <div>
      <h1>{t("help_title")}</h1>
      <Accordion.Root type="multiple" defaultValue={["what", "privacy"]}>
        {sections.map(([value, title, paragraphs]) => (
          <Accordion.Item key={value} value={value} className="help-section">
            <Accordion.Header>
              <Accordion.Trigger className="plain">
                <h3>{t(title)}</h3>
              </Accordion.Trigger>
            </Accordion.Header>
            <Accordion.Content>
              {paragraphs.map((p) => (
                <p key={p}>{p}</p>
              ))}
            </Accordion.Content>
          </Accordion.Item>
        ))}
      </Accordion.Root>
      <section className="help-section">
        <h3>{t("help_words")}</h3>
        <ul className="glossary">
          {["help_word_light", "help_word_conf", "help_word_hidden", "help_word_model"].map((k) => (
            <li key={k}>{t(k)}</li>
          ))}
        </ul>
      </section>
      <section className="help-section">
        <h3>{t("help_delete")}</h3>
        <p>{t("help_delete_text")}</p>
      </section>
    </div>
  );
}
