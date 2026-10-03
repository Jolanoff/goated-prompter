# Frontend direction: the prompt studio

Goated Prompter is a local writing tool for image and video creators, not an
image-generation service. The interface should give the idea, editable prompt,
and creative choices room to breathe without hiding power-user functionality.

## Tokens

- Canvas `#0e1721`: deep-blue workspace background.
- Surface `#152230`: raised editing surfaces, without gradient washes.
- Ink `#e6edf5`: high-contrast writing and interface text.
- Steel `#a3b4c6`: readable secondary text.
- Cobalt `#2860d5`: solid primary actions with white text.
- Ice `#8db8ff`: selection accents and keyboard focus.

Dark mode is the explicit product default, even when the OS prefers light.
The optional light palette uses cool whites and the same hierarchy; an explicit
theme choice is saved only in browser storage, separate from workspace settings.

Manrope is the geometric heading/brand face; DM Sans is the readable interface
and prompt-writing face. Monospace is reserved for actual request logs and
instruction code, not every generated prompt. Body text starts at 14px,
controls at 13px (16px on mobile to avoid input zoom), supporting text at 12px.
Long descriptions stay under 75ch.

## Layout

Left-aligned, persistent navigation frames a generous working canvas. Builder
puts the idea and controls beside the editable result, with references beneath
the result. The action dock is compact, not a second hero.

```text
Desktop
┌──────────────┬───────────────────────────────────────┐
│ Brand        │ Workspace / current workflow          │
│              ├───────────────────────────────────────┤
│ Create       │ Title + short task guidance           │
│ Refine       │                                       │
│ Video        │ Idea                Editable result   │
│ Dataset      │ Controls            References        │
│              │ Rules               Reference mapping │
│ Library      │                                       │
│ Setup        ├───────────────────────────────────────┤
│ Local status │ Generate                  Cancel      │
└──────────────┴───────────────────────────────────────┘

Mobile
┌─────────────────────────────┐
│ Brand                       │
│ Scrollable workflow tabs    │
├─────────────────────────────┤
│ Current workflow            │
│ Title                       │
│ Idea / result / controls    │
│ References / rules          │
├─────────────────────────────┤
│ Generate          Cancel    │
└─────────────────────────────┘
```

## Review before implementation

The user's requested default is dark. Keep a layered blue studio rather than the
original purple-gradient dashboard: clear separation between the canvas, editing
surfaces, controls, and solid cobalt actions. A light editing palette remains an
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
