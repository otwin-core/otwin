# Otwin visual identity

Otwin's image is that of a measuring instrument: neutral chrome, colour only
with meaning, and the data as the subject. The brand violet is a deliberate
bet on standing apart from the sector's blues. This guide governs everything
produced for otwin-core — READMEs, documentation, charts, tables, diagrams,
slides, the website — and any person or agent that touches the project
follows it. The masters live in [`assets/brand`](assets/brand).

## Principles

1. **Chrome is neutral; colour belongs to the content and the brand.**
   Everything around the data uses the surfaces, the ink and the grey scale.
   Colour appears only with a fixed meaning, plus the brand violet as a
   occasional accent. A colour never appears because it looks good.
2. **Every colour always means the same thing.** Ink is what was measured,
   violet is the model, dark grey is what was learned from data, dark orange
   is something to correct, crimson is exceptional failure, the loud green is
   what was validated.
3. **A warning and an alarm are not the same.** Red reads as failure and
   disaster; dark orange reads as something to correct. So `warn` covers
   warnings and most alarms (an operating threshold exceeded, a deviation, a
   parameter out of the expected range) and `alarm` is reserved for the
   exceptional: a legal or safety limit exceeded, a real failure, a refusal.
   If a red appears often, it is being misused.
4. **Showing the limit is part of the identity.** Every figure that can carry
   its uncertainty band carries it, and limits are drawn and labelled.
5. **Every detail comes from the scale.** Sizes, spacing and radii come from
   the tokens below.

## Colour tokens

| Token | Light | Dark | Use |
|---|---|---|---|
| `surface` | `#ffffff` | `#0e0e12` | Background |
| `surface-raised` | `#f5f5f7` | `#1a1a20` | Panels, shaded regions |
| `hairline` | `#d2d2d7` | `#35353c` | Grid lines, row rules |
| `border` | `#86868b` | `#7b7b82` | Borders that mean something |
| `muted` | `#6e6e73` | `#98989f` | Ticks, captions, units |
| `text-secondary` | `#515154` | `#c6c6cc` | Secondary text |
| `ink` | `#1d1d1f` | `#f5f5f7` | Text, and the **measured** series |
| `brand` = `model` | `#7a2ffc` | `#a07bff` | The logo, the accent, the model |
| `data` | `#52525b` | `#b0b0b8` | Series learned from data (solid line) |
| `baseline` | = `muted` | = `muted` | Baselines, always dashed |
| `warn` | `#b45309` | `#e08a3c` | Warnings and most alarms |
| `alarm` | `#b8102e` | `#ff5c6a` | Exceptional alarms only |
| `success` | `#c6ff3d` | `#c6ff3d` | Validated (chip fill or on dark only) |
| `band-model` | `#efe6ff` | `#221440` | The model's uncertainty band |
| `band-data` | `#eaeaeb` | `#26262b` | The data series' band |

Hard rules for the green: `success` is never text on a light background
(1.2:1). It is a chip fill with the text in `ink` (14.2:1), or a full colour
on a dark background (16.3:1). `success` next to `alarm` always carries a
word; they are never distinguished by hue alone. Scalar fields use viridis;
diverging fields use violet–white–orange with white at the neutral value.
Never jet, never rainbow.

## Logo and favicon

The wordmark is `otwin` in lowercase, geometric and heavy, cut horizontally
through the middle of the x-height: the two halves are the twin. The cut is a
GAP, not a painted line — the background shows through it on any surface. The
upper half is slightly thinner than the lower; that is a deliberate optical
correction and is never "fixed". The favicon is the cut `o` alone, same rule.

Uses: violet on light `surface`, white on dark or violet backgrounds, ink
when the context demands monochrome. It is never retyped, never recoloured
outside those three, never given a shadow or outline, and `alarm` never
touches the logo. Masters: `logo.svg` (violet), `logo-white.svg`,
`logo-ink.svg`, `favicon.svg`, plus the full PNG/ICO size set for web,
GitHub, iOS and Android, all in `assets/brand`.

## Component icons

Every library component has an icon and all belong to one family: an ink
circle — the twin, the `o` of the logo — with the concept drawn inside or
across it, stroke 2.4 on a 64-unit grid, round caps, no fills. Each icon
carries a single `brand` accent and no other colour. The set lives in
`assets/brand/icons`, each with a `-dark` variant (white ink, dark-theme
violet) for dark backgrounds; in READMEs they are used at 26 px inside a
`<picture>` element that picks the variant by theme. A new icon is drawn with
these same rules.

## Typography

Everything is set in Helvetica Neue (Liberation Sans as the free fallback),
weights 400 and 700. The wordmark is a drawing, not text: place the file,
never type "otwin" in its style. The figures rule: any number that gets
compared — tables, axes, dashboards — is set in a monospaced face, aligned
right.

## Spacing and radii

8 px base. Charts, tables, images and diagrams are square-cornered; buttons
6 px; cards 10 px. No drop shadows: depth comes from `surface-raised` and
`hairline`.

## Charts

`assets/brand/otwin.mplstyle` carries the Matplotlib defaults. The rules:

1. `surface` background; no top or right spine; horizontal grid only, in
   `hairline`.
2. The title is the finding, in plain language; below it one subtitle line in
   `muted` with what was measured and on how many data.
3. The measured series is `ink` dots; the model is a `model` (violet) line
   with its band at 12 % opacity; data-learned series are solid `data`;
   baselines are dashed `baseline`. Series are labelled directly at their
   ends, in their colour.
4. Operating thresholds in `warn` and exceptional limits in `alarm`, always
   dashed, always with a label and the value. The training region is shaded
   `surface-raised` with a `border` line at the split, labelled "training"
   and "unseen".
5. Ticks in mono, `muted`. Export at 160 dpi on white, or SVG.

## Tables

No vertical rules, no zebra; rows separated by `hairline`, the header in 700
over a `border` rule, units in `muted`. Figures in mono, right-aligned.
A block's border is the same on all four sides: a coloured margin on one side
of a card, a note or a table row is not used. The kind of a note is carried by
its title, in the colour of its token.
States: "validated" as a `success` chip with `ink` text; "warning" as a word
in `warn`; "rejected" or "failure" as a word in `alarm`. Never a fully
coloured cell.

## Diagrams

Mermaid with `assets/brand/mermaid-config.json`: `surface` nodes with a
1.5 px `ink` outline, straight edges, transparent background. One element may
be highlighted in `brand`. Corners at 6 px at most.

## Imagery

Otwin's image is the result over the real equipment: a chart with its band,
or a technical photograph or render of the equipment with the measurement
layer on top. Banned: flat infographic illustration, isometric toy drawings,
generic stock, gradients, emojis. Without a real photograph, a chart alone is
a better image than any illustration.

When a page needs the equipment itself, as the tutorials do, it is a
technical drawing, the kind an engineer would get from a CAD drawing sheet:
an elevation, a section or a plan on a white sheet with a title block.
Centerlines are dash-dot, material cut by the section is hatched at 45°,
dimensions are real and the parameters the model uses are written as
callouts with their values. Lines are `ink`, fills `surface-raised`; one ISA
instrument bubble in `brand` marks what is measured, and it is the only
colour on the sheet. All of them are drawn from code, in
`assets/tutorials/make_art.py`.

## Documentation site

The documentation at otwin.readthedocs.io keeps the structure of
pydata-sphinx-theme (navigation, search, the light and dark switch) and takes
everything visual from these tokens, in `docs/_static/custom.css`: the
surfaces, ink and grey scale, the brand violet for links and the active
section, the type, square code blocks and tables, cards at 10 px without
shadows. The logo and favicon are referenced from `assets/brand`, never
copied. Code is highlighted in the grey scale, because syntax colour would be
colour without meaning. Diagrams take `assets/brand/mermaid-config.json`.

## Voice

Plain declarative sentences a plant engineer reads in seconds. The measured
figure replaces the adjective. No slogans, no claims, never the word
"honest", headings without jargon. The name is `otwin` in the wordmark and
Otwin in prose.
