"""Every sentence the wizard's engine writes, in English and Spanish.

``t(key, lang, **values)`` returns the sentence in ``lang`` with the values
put in. A key missing in Spanish falls back to English (and a test fails),
so the page never shows a key. Numbers are formatted by the caller: the
Spanish texts take them already formatted with :func:`num`.
"""

from __future__ import annotations

__all__ = ["t", "num", "MONTHS", "TEXTS", "LANGUAGES"]

LANGUAGES = ("en", "es")

MONTHS = {
    "en": (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ),
    "es": (
        "ene",
        "feb",
        "mar",
        "abr",
        "may",
        "jun",
        "jul",
        "ago",
        "sep",
        "oct",
        "nov",
        "dic",
    ),
}


def num(x: float, lang: str, digits: int = 0) -> str:
    """A number as each language writes it: 2,958.5 in English, 2.958,5 in Spanish."""
    text = f"{x:,.{digits}f}"
    if lang == "es":
        if abs(x) < 10_000:  # 2958, not 2.958: four digits take no separator
            text = f"{x:.{digits}f}"
        text = text.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return text


def t(key: str, lang: str = "en", **values: object) -> str:
    """The sentence ``key`` in ``lang``, with ``values`` put in."""
    entry = TEXTS[key]
    template = entry.get(lang) or entry["en"]
    return template.format(**values)


TEXTS: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------ files
    "to": {"en": "to", "es": "a"},
    "no_readings": {"en": "no readings", "es": "sin lecturas"},
    "readings_from": {
        "en": "{step}{what}, {n} readings from {span}{total}",
        "es": "{what}{step}, {n} lecturas del {span}{total}",
    },
    "hourly_": {"en": "hourly ", "es": " por horas"},
    "quarter_hourly_": {"en": "quarter-hourly ", "es": " cuartohoraria"},
    "range_c": {"en": ", {lo} to {hi} °C", "es": ", de {lo} a {hi} °C"},
    "read_as": {
        "en": "Read as {format}: {parts}.",
        "es": "Leído como {format}: {parts}.",
    },
    "bill_line": {
        "en": "{first} to {last}, {m3} m³",
        "es": "del {first} al {last}, {m3} m³",
    },
    "charged_as": {"en": " charged as {kwh} kWh", "es": " facturados como {kwh} kWh"},
    "read_bills": {
        "en": "Read {n} {what} {bills}: {parts}.",
        "es": "{leidas} {n} {bills} de {what}: {parts}.",
    },
    "gas": {"en": "gas", "es": "gas"},
    "water": {"en": "water", "es": "agua"},
    "bill": {"en": "bill", "es": "factura"},
    "bills": {"en": "bills", "es": "facturas"},
    "file_unreadable": {
        "en": "This file could not be read: {detail}",
        "es": "No hemos podido leer este archivo: {detail}",
    },
    "file_layout": {
        "en": "We don't know this layout. Tell us which column is which.",
        "es": "No conocemos este formato. Dinos qué columna es cada cosa.",
    },
    "ha_history": {
        "en": (
            "Home Assistant history files carry no units. Export long-term statistics "
            "instead (they include units), or use the column mapper on a CSV."
        ),
        "es": (
            "Los archivos de historial de Home Assistant no llevan unidades. Exporta "
            "las estadísticas a largo plazo (sí las llevan) o usa el lector de columnas."
        ),
    },
    "mapping_failed": {
        "en": "Those columns did not work: {detail}",
        "es": "Esas columnas no han funcionado: {detail}",
    },
    "bill_unreadable": {
        "en": "This bill could not be read. {detail}",
        "es": "No hemos podido leer esta factura. {detail}",
    },
    "check_field": {
        "en": "Check the {field}: {detail}",
        "es": "Revisa {field}: {detail}",
    },
    # formats and quantities
    "fmt_datadis_json": {"en": "Datadis download", "es": "descarga de Datadis"},
    "fmt_distributor_csv": {
        "en": "hourly electricity from Datadis or your distributor",
        "es": "consumo eléctrico de Datadis o de tu distribuidora",
    },
    "fmt_ide_csv": {
        "en": "i-DE (Iberdrola) consumption file",
        "es": "archivo de consumo de i-DE (Iberdrola)",
    },
    "fmt_shelly_csv": {
        "en": "Shelly meter export",
        "es": "exportación de un medidor Shelly",
    },
    "fmt_tapo_xlsx": {"en": "Tapo plug export", "es": "exportación de un enchufe Tapo"},
    "fmt_ha_statistics": {
        "en": "Home Assistant statistics",
        "es": "estadísticas de Home Assistant",
    },
    "fmt_ha_history": {
        "en": "Home Assistant history",
        "es": "historial de Home Assistant",
    },
    "fmt_gas_bills": {"en": "gas bills", "es": "facturas de gas"},
    "fmt_water_bills": {"en": "water bills", "es": "facturas de agua"},
    "fmt_typed_gas": {
        "en": "a gas bill typed in",
        "es": "una factura de gas escrita a mano",
    },
    "fmt_typed_water": {
        "en": "a water bill typed in",
        "es": "una factura de agua escrita a mano",
    },
    "fmt_open_meteo_json": {"en": "Open-Meteo weather", "es": "tiempo de Open-Meteo"},
    "fmt_open_meteo_csv": {"en": "Open-Meteo weather", "es": "tiempo de Open-Meteo"},
    "fmt_mapped": {"en": "your own columns", "es": "tus propias columnas"},
    "q_electricity_import": {
        "en": "electricity from the grid",
        "es": "electricidad de la red",
    },
    "q_electricity_export": {
        "en": "electricity sent to the grid",
        "es": "electricidad vertida a la red",
    },
    "q_electricity_self_consumption": {
        "en": "solar electricity used at home",
        "es": "electricidad solar autoconsumida",
    },
    "q_plug_energy": {
        "en": "smart-plug energy",
        "es": "energía de un enchufe inteligente",
    },
    "q_plug_power": {
        "en": "smart-plug power",
        "es": "potencia de un enchufe inteligente",
    },
    "q_gas_energy": {"en": "gas (kWh billed)", "es": "gas (kWh facturados)"},
    "q_gas_volume": {"en": "gas (m³)", "es": "gas (m³)"},
    "q_water_volume": {"en": "water", "es": "agua"},
    "q_electricity_cost": {"en": "electricity cost", "es": "coste de la electricidad"},
    "q_gas_cost": {"en": "gas cost", "es": "coste del gas"},
    "q_water_cost": {"en": "water cost", "es": "coste del agua"},
    "q_outdoor_temperature": {"en": "outdoor temperature", "es": "temperatura exterior"},
    "q_indoor_temperature": {
        "en": "indoor temperature (interior thermometer)",
        "es": "temperatura interior (termómetro)",
    },
    "q_solar_irradiance": {"en": "sunshine", "es": "radiación solar"},
    # bill form fields
    "field_inicio": {"en": "first reading date", "es": "la fecha de la primera lectura"},
    "field_fin": {"en": "last reading date", "es": "la fecha de la última lectura"},
    "field_m3": {"en": "m³", "es": "los m³"},
    "field_fc": {"en": "conversion factor (Fc)", "es": "el factor de conversión (Fc)"},
    "field_pcs_kwh_m3": {
        "en": "calorific value (PCS)",
        "es": "el poder calorífico (PCS)",
    },
    "field_kwh": {"en": "kWh", "es": "los kWh"},
    "field_importe_eur": {"en": "amount", "es": "el importe"},
    "typed_bill_name": {
        "en": "{what}, {first} to {last} (typed in)",
        "es": "{what}, {first} a {last} (escrita a mano)",
    },
    "gas_bill_title": {"en": "Gas bill", "es": "Factura de gas"},
    "electricity_bill_title": {"en": "Electricity bill", "es": "Factura de electricidad"},
    "fmt_typed_electricity": {
        "en": "an electricity bill typed in",
        "es": "una factura de electricidad escrita a mano",
    },
    "read_electricity_bill": {
        "en": "Electricity bill, {first} to {last}: {kwh} kWh{eur}.",
        "es": "Factura de electricidad, del {first} al {last}: {kwh} kWh{eur}.",
    },
    "for_eur": {"en": ", {eur} €", "es": ", {eur} €"},
    # ------------------------------------------------------- do the bills fit the home?
    "gas_implausible": {
        "en": "These gas bills show about {bill} kWh a day. A home as you described it would use about {typical} kWh a day in January. Either the bills are from another home, or the answers do not describe this one.",
        "es": "Estas facturas de gas muestran unos {bill} kWh al día. Una casa como la que has descrito gastaría unos {typical} kWh al día en enero. O las facturas son de otra casa, o las respuestas no describen esta.",
    },
    "gas_but_no_gas": {
        "en": "There are gas bills, but nothing in the home you described runs on gas. Either the bills are from another home, or the answers do not describe this one.",
        "es": "Hay facturas de gas, pero en la casa que has descrito nada funciona con gas. O las facturas son de otra casa, o las respuestas no describen esta.",
    },
    "elec_implausible": {
        "en": "This electricity record shows about {record} kWh a day. A home as you described it would use about {typical} kWh a day in January. Either the file is from another home, or the answers do not describe this one.",
        "es": "Este registro de electricidad muestra unos {record} kWh al día. Una casa como la que has descrito gastaría unos {typical} kWh al día en enero. O el archivo es de otra casa, o las respuestas no describen esta.",
    },
    # ------------------------------------------------------- reading a bill
    "inv_kind_electricity": {
        "en": "an electricity bill",
        "es": "una factura de electricidad",
    },
    "inv_kind_gas": {"en": "a gas bill", "es": "una factura de gas"},
    "inv_kind_water": {"en": "a water bill", "es": "una factura de agua"},
    "inv_kind_unknown": {
        "en": "a bill we could not place",
        "es": "una factura que no sabemos ubicar",
    },
    "inv_from": {"en": " from {supplier}", "es": " de {supplier}"},
    "inv_read": {
        "en": "This looks like {kind}{from}{period}{amounts}. Check the fields and add it.",
        "es": "Parece {kind}{from}{period}{amounts}. Revisa los campos y añádela.",
    },
    "inv_period": {"en": ", {first} to {last}", "es": ", del {first} al {last}"},
    "inv_nothing": {
        "en": "We could not read the numbers on this document. Type them in from the paper, or try a sharper photo.",
        "es": "No hemos podido leer los números de este documento. Escríbelos del papel, o prueba con una foto más nítida.",
    },
    "inv_kwh_mismatch": {
        "en": "m³ × Fc × PCS does not give the kWh read: one of them is misread.",
        "es": "m³ × Fc × PCS no da los kWh leídos: alguno está mal leído.",
    },
    "water_bill_title": {"en": "Water bill", "es": "Factura de agua"},
    # ------------------------------------------------------------ the example
    "example_remade": {
        "en": (
            "The example home was simulated again with your answers ({day} °C by day, "
            "{night}): its electricity, gas bill and interior thermometer now follow them."
        ),
        "es": (
            "La casa de ejemplo se ha simulado de nuevo con tus respuestas ({day} °C de "
            "día, {night}): su electricidad, su factura de gas y su termómetro interior "
            "las siguen ahora."
        ),
    },
    "night_lower": {"en": "16 °C at night", "es": "16 °C de noche"},
    "night_same": {"en": "{day} °C at night too", "es": "{day} °C también de noche"},
    # ------------------------------------------------------------ gas, water, heating
    "gas_bill_one": {
        "en": (
            "Your gas bill, {period}: {m3} m³, charged as {kwh} kWh ({factor} kWh per "
            "m³, the conversion printed on your bill)."
        ),
        "es": (
            "Tu factura de gas, {period}: {m3} m³, facturados como {kwh} kWh ({factor} "
            "kWh por m³, la conversión que viene en tu factura)."
        ),
    },
    "gas_twin_one": {
        "en": "Your twin used {kwh} kWh over the same dates, which at your bill's conversion is {m3} m³: {how}",
        "es": "Tu modelo usó {kwh} kWh en las mismas fechas, que con la conversión de tu factura son {m3} m³: {how}",
    },
    "almost_exactly": {"en": "almost exactly", "es": "casi exactamente"},
    "pct_more": {"en": "{pct} % more", "es": "un {pct} % más"},
    "pct_less": {"en": "{pct} % less", "es": "un {pct} % menos"},
    "than_the_bill": {"en": " than the bill.", "es": " que la factura."},
    "what_you_were_billed": {
        "en": " what you were billed.",
        "es": " lo que te facturaron.",
    },
    "by_design": {
        "en": (
            " That is by design: the twin was fitted to this bill, which is how it "
            "measured how fast your home loses heat."
        ),
        "es": (
            " Es a propósito: el modelo se ajustó a esta factura, y así midió lo rápido "
            "que tu casa pierde calor."
        ),
    },
    "gas_line_many": {
        "en": "{period}: billed {m3} m³ = {kwh} kWh ({factor} kWh per m³ on that bill); your twin {twin_kwh} kWh = {twin_m3} m³.",
        "es": "{period}: facturados {m3} m³ = {kwh} kWh ({factor} kWh por m³ en esa factura); tu modelo {twin_kwh} kWh = {twin_m3} m³.",
    },
    "gas_many_agree": {
        "en": (
            "One twin, fitted to all {n} bills at once, reproduces each of them: your "
            "home behaves the same way in mild and in cold weather, which is what makes "
            "its numbers trustworthy."
        ),
        "es": (
            "Un solo modelo, ajustado a las {n} facturas a la vez, reproduce cada una: "
            "tu casa se comporta igual con tiempo suave y con frío, y eso hace fiables "
            "sus números."
        ),
    },
    "gas_many_disagree": {
        "en": (
            "One twin, fitted to all {n} bills at once, does not reproduce each of them "
            "equally well: something in your home changes between these periods (the "
            "thermostat, who is at home, the hot water)."
        ),
        "es": (
            "Un solo modelo, ajustado a las {n} facturas a la vez, no reproduce todas "
            "igual de bien: algo cambia en tu casa entre estos periodos (el termostato, "
            "quién está en casa, el agua caliente)."
        ),
    },
    "gas_no_bill": {
        "en": (
            "No gas bill covers these dates. With typical use, your twin expects about "
            "{kwh} kWh of gas over them, about {m3} m³ at a usual 10.7 kWh per m³."
        ),
        "es": (
            "Ninguna factura de gas cubre estas fechas. Con un uso típico, tu modelo "
            "espera unos {kwh} kWh de gas, unos {m3} m³ a los 10,7 kWh por m³ habituales."
        ),
    },
    "gas_not_fitted": {
        "en": (
            "Your heating is not on gas, so the bill was not used to fit the twin; it "
            "checks the twin's typical hot water and cooking against what you used."
        ),
        "es": (
            "Tu calefacción no es de gas, así que la factura no se usó para ajustar el "
            "modelo: sirve para comparar el agua caliente y la cocina típicas con lo "
            "que gastaste."
        ),
    },
    "gas_shares": {
        "en": "Where your gas goes, by the twin: {shares}.",
        "es": "Adónde va tu gas, según el modelo: {shares}.",
    },
    "use_heating": {"en": "heating", "es": "calefacción"},
    "use_hot water": {"en": "hot water", "es": "agua caliente"},
    "use_cooking": {"en": "cooking", "es": "cocina"},
    "use_always_on": {"en": "always on", "es": "siempre encendido"},
    "use_appliances": {"en": "appliances", "es": "electrodomésticos"},
    "use_cooling": {"en": "air conditioning", "es": "aire acondicionado"},
    "water_one": {
        "en": "Your water bill, {period}",
        "es": "Tu factura del agua, {period}",
    },
    "water_many": {
        "en": "Your water bills ({periods})",
        "es": "Tus facturas del agua ({periods})",
    },
    "water_total": {
        "en": "{when}: {m3} m³ in {days} days, about {per_day} litres a day.",
        "es": "{when}: {m3} m³ en {days} días, unos {per_day} litros al día.",
    },
    "water_typical": {
        "en": "about what a typical Spanish home uses",
        "es": "más o menos lo que gasta un hogar típico en España",
    },
    "water_more": {
        "en": "{pct} % more than a typical Spanish home",
        "es": "un {pct} % más que un hogar típico en España",
    },
    "water_less": {
        "en": "{pct} % less than a typical Spanish home",
        "es": "un {pct} % menos que un hogar típico en España",
    },
    "water_each": {
        "en": "That is {each} litres per person a day, {compare} (about {typical} litres per person).",
        "es": "Son {each} litros por persona al día, {compare} (unos {typical} litros por persona).",
    },
    "water_one_person": {
        "en": "That is {compare} (about {typical} litres per person a day).",
        "es": "Es {compare} (unos {typical} litros por persona al día).",
    },
    "radiates": {
        "en": "Your home radiates about {w} W to the cold night sky, {where}: {pct} % of its heat loss on a 5 °C day with 20 °C inside.",
        "es": "Tu casa irradia unos {w} W al cielo frío de la noche, {where}: el {pct} % de lo que pierde un día de 5 °C con 20 °C dentro.",
    },
    "radiates_flat": {
        "en": "through its facades (its roof and floor are its neighbours')",
        "es": "por sus fachadas (su techo y su suelo son los de los vecinos)",
    },
    "radiates_house": {
        "en": "mostly through its roof, which sees the whole night sky",
        "es": "sobre todo por el tejado, que ve todo el cielo de la noche",
    },
    "thermostat_ran": {
        "en": "Your thermostat called for heat about {hours} hours a day, and your {machine} ran {pct} % of the time ({full} hours a day at full power).",
        "es": "Tu termostato pidió calor unas {hours} horas al día, y tu {machine} funcionó el {pct} % del tiempo ({full} horas al día a plena potencia).",
    },
    "machine_gas": {"en": "boiler", "es": "caldera"},
    "machine_heat_pump": {"en": "heat pump", "es": "bomba de calor"},
    "machine_electric": {"en": "heaters", "es": "radiadores"},
    "machine_none": {"en": "heating", "es": "calefacción"},
}


# ------------------------------------------------------------ the "My home" dashboard
TEXTS.update(
    {
        # the header line
        "kind_flat": {"en": "flat", "es": "piso"},
        "kind_terraced": {"en": "terraced house", "es": "casa adosada"},
        "kind_detached": {"en": "detached house", "es": "casa independiente"},
        "heat_heat_pump": {"en": "heat pump", "es": "bomba de calor"},
        "heat_electric": {"en": "electric heaters", "es": "radiadores eléctricos"},
        "heat_gas": {"en": "gas boiler", "es": "caldera de gas"},
        "heat_none": {"en": "no heating", "es": "sin calefacción"},
        # card lines
        "card_period": {"en": "{period} · {amount}", "es": "{period} · {amount}"},
        "card_days_short": {
            "en": "Only {days} days so far: the analysis needs at least {need}.",
            "es": "De momento solo {days} días: el análisis necesita al menos {need}.",
        },
        "card_bill": {"en": "{period} · {m3} m³", "es": "{period} · {m3} m³"},
        "card_bill_kwh": {
            "en": "{period} · {m3} m³ = {kwh} kWh",
            "es": "{period} · {m3} m³ = {kwh} kWh",
        },
        "card_thermo": {
            "en": "{period} · {lo} to {hi} °C",
            "es": "{period} · de {lo} a {hi} °C",
        },
        "card_weather_files": {
            "en": "{period} · from your files",
            "es": "{period} · de tus archivos",
        },
        # findings, in plain words
        "f_heat_loss": {
            "en": "Your home lets out {w} W for every degree between inside and outside{pm}: about {kw} kW on a 5 °C day with 20 °C inside.",
            "es": "Tu casa deja escapar {w} W por cada grado de diferencia entre dentro y fuera{pm}: unos {kw} kW un día de 5 °C con 20 °C dentro.",
        },
        "f_keeps_warm": {
            "en": "With the heating off, it loses two-thirds of its warmth over the outdoor temperature in about {hours} hours{pm}.",
            "es": "Con la calefacción apagada, pierde dos tercios de su calor sobre la temperatura exterior en unas {hours} horas{pm}.",
        },
        "f_machine": {
            "en": "Your {machine}: {kw} kW of heat at full power{pm}.",
            "es": "Tu {machine}: {kw} kW de calor a plena potencia{pm}.",
        },
        "f_machine_cool": {
            "en": "Your air conditioner: {kw} kW of cooling at full power{pm}.",
            "es": "Tu aire acondicionado: {kw} kW de frío a plena potencia{pm}.",
        },
        "f_base": {
            "en": "{w} W stay on all the time{pm}: about {kwh} kWh a month whatever you do.",
            "es": "{w} W están siempre encendidos{pm}: unos {kwh} kWh al mes hagas lo que hagas.",
        },
        "f_thermo_ok": {
            "en": "Your thermometer reads your home's temperature{pm}.",
            "es": "Tu termómetro lee la temperatura de tu casa{pm}.",
        },
        "f_thermo_off": {
            "en": "Your thermometer reads {k} °C {where} than your home on average{pm}, because of where it hangs or its calibration; the model allows for it.",
            "es": "Tu termómetro marca {k} °C {where} que tu casa de media{pm}, por dónde está o por su calibración; el modelo lo tiene en cuenta.",
        },
        "warmer": {"en": "warmer", "es": "más"},
        "cooler": {"en": "cooler", "es": "menos"},
        "not_measured": {"en": "Not measured.", "es": "No medido."},
        "label_heat_loss": {
            "en": "How fast your home loses heat",
            "es": "Lo rápido que tu casa pierde calor",
        },
        "label_keeps_warm": {
            "en": "How long it stays warm",
            "es": "Cuánto tiempo guarda el calor",
        },
        "label_machine": {"en": "Size of your {machine}", "es": "Tamaño de tu {machine}"},
        "label_cooler": {
            "en": "Size of your air conditioner",
            "es": "Tamaño de tu aire acondicionado",
        },
        "label_base": {
            "en": "What stays on all the time",
            "es": "Lo que está siempre encendido",
        },
        "label_thermo": {"en": "Your thermometer", "es": "Tu termómetro"},
        # reasons
        "r_gas_no_bills": {
            "en": "Your heating runs on gas, so electricity cannot show how your home gains or loses heat. Add your gas bills.",
            "es": "Tu calefacción es de gas, así que la electricidad no muestra cómo gana o pierde calor tu casa. Añade tus facturas de gas.",
        },
        "r_bills_storage": {
            "en": "Gas bills show totals over weeks, not how quickly your home cools. An interior thermometer would show it.",
            "es": "Las facturas de gas dan totales de semanas, no lo rápido que se enfría tu casa. Un termómetro interior lo mostraría.",
        },
        "r_bills_size": {
            "en": "Gas bills show totals over weeks, not the peaks that show your boiler's size. An interior thermometer would show it.",
            "es": "Las facturas de gas dan totales de semanas, no los picos que muestran el tamaño de tu caldera. Un termómetro interior lo mostraría.",
        },
        "r_no_heating": {
            "en": "Your home has no heating or cooling in the model, so the meters cannot show how it gains or loses heat.",
            "es": "Tu casa no tiene calefacción ni aire en el modelo, así que los contadores no muestran cómo gana o pierde calor.",
        },
        "r_no_electricity": {
            "en": "No hourly electricity was given. Add a month of it.",
            "es": "No hay consumo eléctrico por horas. Añade un mes.",
        },
        "r_full_power": {
            "en": "It never ran at full power, so its full size never showed: it is bigger than these days needed.",
            "es": "Nunca funcionó a plena potencia, así que su tamaño no se ha visto: es más grande de lo que hizo falta.",
        },
        "r_no_storage": {
            "en": "It shows only when the indoor temperature changes, and here it hardly did. A lower setting at night would show it.",
            "es": "Solo se ve cuando cambia la temperatura de dentro, y aquí apenas cambió. Una temperatura más baja por la noche lo mostraría.",
        },
        "r_unstable": {
            "en": "Different parts of your data point to different values.",
            "es": "Distintas partes de tus datos apuntan a valores distintos.",
        },
        "r_not_pinned": {
            "en": "Your data does not pin this down yet; more would.",
            "es": "Tus datos todavía no lo concretan; más datos sí lo harían.",
        },
        # confidence
        "conf_reliable": {
            "en": "Reliable: the model matches {sources}, and every number it measured is well determined.",
            "es": "Fiable: el modelo coincide con {sources}, y cada número que midió está bien determinado.",
        },
        "conf_approximate": {
            "en": "Approximate: the model matches {sources}. Known well: {good}. Only roughly: {rough}.",
            "es": "Aproximado: el modelo coincide con {sources}. Bien conocido: {good}. Solo aproximado: {rough}.",
        },
        "conf_more": {
            "en": "We need more data for {poor}. The model does match {sources}.",
            "es": "Necesitamos más datos para {poor}. El modelo sí coincide con {sources}.",
        },
        "conf_mismatch": {
            "en": "We need more data: the model does not yet reproduce {what}. Check your answers about the home: something that uses a lot of energy may be missing.",
            "es": "Necesitamos más datos: el modelo todavía no reproduce {what}. Revisa las respuestas sobre tu casa: puede faltar algo que gaste mucha energía.",
        },
        "src_electricity": {"en": "your electricity", "es": "tu electricidad"},
        "src_bills": {"en": "your gas bills", "es": "tus facturas de gas"},
        "src_bill": {"en": "your gas bill", "es": "tu factura de gas"},
        "src_indoor": {"en": "your indoor temperature", "es": "tu temperatura interior"},
        "nothing_yet": {"en": "nothing yet", "es": "nada todavía"},
        "and": {"en": "and", "es": "y"},
        # what if
        "wi_thermostat_down": {
            "en": "Thermostat 1 °C lower",
            "es": "Termostato 1 °C más bajo",
        },
        "wi_thermostat_up": {
            "en": "Thermostat 1 °C higher",
            "es": "Termostato 1 °C más alto",
        },
        "wi_insulate": {
            "en": "Insulate walls{roof} (about 8 cm)",
            "es": "Aislar paredes{roof} (unos 8 cm)",
        },
        "wi_roof": {"en": " and roof", "es": " y tejado"},
        "wi_colder": {"en": "A winter 2 °C colder", "es": "Un invierno 2 °C más frío"},
        "wi_saves": {
            "en": "saves about {eur} € a month",
            "es": "ahorra unos {eur} € al mes",
        },
        "wi_costs": {
            "en": "costs about {eur} € more a month",
            "es": "cuesta unos {eur} € más al mes",
        },
        "wi_same": {"en": "about the same cost", "es": "más o menos el mismo coste"},
        "wi_basis": {
            "en": "Worked out on {period}, at typical prices.",
            "es": "Calculado sobre {period}, a precios típicos.",
        },
        # the hidden-month test
        "trust_needs_two": {
            "en": "Add another month of data: then we hide one month from the model and ask it to guess it.",
            "es": "Añade otro mes de datos: entonces escondemos un mes al modelo y le pedimos que lo adivine.",
        },
        "trust_intro": {
            "en": "We hid {period} from the model, let it learn from the other months, and asked it to guess the hidden one.",
            "es": "Escondimos al modelo el periodo {period}, le dejamos aprender con los otros meses y le pedimos que lo adivinara.",
        },
        "trust_gas": {
            "en": "Gas: it guessed {guess} kWh; your bill says {real} kWh ({off}).",
            "es": "Gas: adivinó {guess} kWh; tu factura dice {real} kWh ({off}).",
        },
        "trust_elec": {
            "en": "Electricity: it guessed {guess} kWh; your meter says {real} kWh ({off}).",
            "es": "Electricidad: adivinó {guess} kWh; tu contador dice {real} kWh ({off}).",
        },
        "trust_indoor": {
            "en": "Indoor temperature: a typical hour within {k} °C of your thermometer.",
            "es": "Temperatura interior: una hora típica a menos de {k} °C de tu termómetro.",
        },
        "pct_off": {"en": "{pct} % off", "es": "un {pct} % de diferencia"},
        "trust_pass": {
            "en": "Passed: the model predicts a month it never saw.",
            "es": "Superado: el modelo predice un mes que nunca vio.",
        },
        "trust_fail": {
            "en": "Not passed: the hidden month differs more than expected. Something may change between your months (the thermostat, who is at home).",
            "es": "No superado: el mes escondido difiere más de lo esperado. Puede que algo cambie entre tus meses (el termostato, quién está en casa).",
        },
    }
)
