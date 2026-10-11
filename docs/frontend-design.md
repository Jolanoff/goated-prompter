# Frontend direction: the prompt studio

Goated Prompter is a local writing tool for image and video creators, not an
image-generation service. The interface should give the idea, editable prompt,
and creative choices room to breathe without hiding power-user functionality.

## Tokens: "Signal"

A warm graphite studio with one electric-lime signal colour. Lime means "go",
"live" and "selected"; everything else stays quiet so the writing leads.

- Rail `#0c0c0b`: navigation, dark in both themes.
- Canvas `#121211` → Surface `#1a1a18` → Raised `#232321`: layered warm
  graphite, no gradients and no blue cast.
- Ink `#f2f0ea`: writing and interface text. Muted `#a8a59c`: secondary text.
- Signal `#d4ff3a`: the primary action (with `#151a00` text), focus ring,
  selection and live status. Use it sparingly: one signal action per region.
- Light theme keeps the hierarchy on warm paper (`#f4f3ef` / `#ffffff`); the
  primary action flips to ink `#1a1a17` with lime text and accent text becomes
  olive `#4a6400` so it stays readable.

Dark mode is the explicit product default, even when the OS prefers light.
An explicit theme choice is saved only in browser storage, separate from
workspace settings.

Bricolage Grotesque is the display face (page titles, panel headings, the
wordmark); Instrument Sans is the interface and prompt-writing face. Both load
from `@fontsource-variable`. Monospace is reserved for request logs and
instruction code. Body text starts at 14px, controls at 13–14px (16px on
mobile to avoid input zoom), supporting text at 12–13px. Shapes are soft:
12px controls, 18px panels, pills for chips and selectors.

## Layout

Left-aligned, persistent navigation frames a generous working canvas. Builder
is a composer beside a document: the idea, its controls (as pill selectors)
and the rules live in one composer card with Generate at its foot; the
result reads like a document with its tools underneath. References sit below
the result as a filmstrip. On mobile the Builder actions pin to a full-width
bar at the bottom of the viewport.

```text
Desktop
┌──────────────┬───────────────────────────────────────┐
│ Brand        │ Breadcrumb            Theme · Status  │
│              │ Title                                 │
│ Builder      ├───────────────────┬───────────────────┤
│ Refine       │ Idea              │ Generated prompt  │
│ MiniMax      │ Pill controls     │ (document)        │
│ Dataset      │ Rules             │ Copy Save Refine  │
│ ──────────── │ Preview · Generate├───────────────────┤
│ Library      │                   │ Reference strip   │
│ Presets      │                   │ Keep from refs    │
│ Settings     │                   │                   │
│ View log     │                   │                   │
└──────────────┴───────────────────┴───────────────────┘

Mobile
┌─────────────────────────────┐
│ Brand                       │
│ Scrollable workflow tabs    │
├─────────────────────────────┤
│ Title                       │
│ Idea / controls / rules     │
│ Result                      │
│ References                  │
├─────────────────────────────┤
│ Stop   Generate prompt      │
└─────────────────────────────┘
```

## Review before implementation

The user's requested default is dark. Keep a layered graphite studio with one
signal colour: clear separation between the canvas, editing surfaces,
controls, and solid lime actions. A light editing palette remains an
optional preference, not the default. Remove decorative mountains,
gradient panel fills, repeated slogans, uppercase eyebrows, and miniature type.
Use borders for grouping and selection, not decoration; vary hierarchy instead
of treating every nested control as an equal card. Keep the existing goat mark.

## Quality floor

Apply shared tokens to every workflow, library, settings page, history, and
dialog. Preserve current data, generation, repair, and persistence behavior.
Check desktop, tablet, and 360px mobile layouts; visible focus, meaningful
navigation names, contrast, reduced motion, safe-area dock spacing, and dialogs
that scroll inside the viewport. Capture screenshots and run interaction tests.
