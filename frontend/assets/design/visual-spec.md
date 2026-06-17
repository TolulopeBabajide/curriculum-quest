# Visual Design Spec — Curriculum Quest

This file contains a compact visual spec for the Curriculum Quest project and two lightweight SVG prototypes (scene + portrait) committed to the repo under frontend/assets/design/.

Overview
- Goal: provide a culturally coherent, accessible, and lightweight visual system for the web client (frontend/index.html) that supports localized scenes, layered art for parallax, and expression-swapping portraits.
- Files added:
  - frontend/assets/design/visual-spec.md  — this spec
  - frontend/assets/design/mockup-scene.svg — prototype layered scene
  - frontend/assets/design/mockup-portrait.svg — prototype portrait with 3 expressions

Color palette (primary accessible warm palette)
- --cq-primary: #0E6A4A  /* deep green — primary accents, buttons */
- --cq-accent:  #F29E4C  /* warm orange — highlights, badges */
- --cq-bg:      #FFF9F2  /* warm cream background */
- --cq-surface: #FFFFFF /* cards */
- --cq-muted:   #6B6B6B /* muted text */
- --cq-danger:  #D9534F  /* errors/negative outcomes */

Accessible contrast notes
- Primary text on surface: #111827 (very dark gray) — ensures readable body copy.
- Ensure >4.5:1 contrast for body text; for large UI text 3:1 is acceptable but try to maintain 4.5:1.

Fonts
- Primary (UI & headings): Inter (variable) — neutral, highly legible for UI. Google: `Inter:400,600,700`.
- Story/Narration: Noto Serif (or Merriweather) — use sparingly for narrative panels when you want a literary feel. Google: `Noto+Serif:400,700`.
- Fallback stack: system fonts for speed: `font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial;`

CSS variables (example)
:root {
  --cq-primary: #0E6A4A;
  --cq-accent:  #F29E4C;
  --cq-bg:      #FFF9F2;
  --cq-surface: #FFFFFF;
  --cq-muted:   #6B6B6B;
  --cq-danger:  #D9534F;
  --cq-radius:  12px;
  --cq-animation-fast: 150ms;
  --cq-animation-medium: 320ms;
}

Scene layout (web client)
- Viewport: responsive card with safe area. Default canvas: 1200x600 (desktop) but scale down responsively.
- Composition (top-to-bottom stacking):
  1. Background sky & horizon (layer: bg)
  2. Distant hills & village silhouette (layer: far)
  3. Midground: market stalls, house, stream (layer: mid)
  4. Foreground: characters, props, interactive hotspots (layer: fg)
  5. UI overlay: narration card, action buttons, progress (absolute overlay)

Layering & assets
- Each scene asset should be exported as an independent layer/group with a stable id, e.g. `layer-bg`, `layer-far`, `layer-mid`, `layer-fg`, `layer-fg-characters`.
- Naming convention for files: `scenes/<scene-key>/<scene-key>-layer-<name>.png|svg`. Example: `scenes/market/market-layer-mid.png`.
- Portraits: `portraits/<agent>-idle.png`, `<agent>-happy.png`, `<agent>-concerned.png`.

Animation & parallax
- Parallax: translateX/translateY small amounts on scroll or when pointer moves (max 8–16px for subtlety).
- Use CSS transform with will-change: transform; hardware accelerated.
- Respect `prefers-reduced-motion`.

Microinteractions
- Button press: scale(0.98) & subtle shadow change at 120–160ms.
- Correct answer: short confetti-like burst using CSS + small particle SVGs (duration ~600ms).

Accessibility
- Provide aria-live region for narration stream.
- Each scene has alt text and a short transcript of the last narration card.
- Keyboard accessible hotspots: use role=button, tabindex=0, and visible focus ring.

Asset sizing recommendations
- Portrait masters: 1024x1024 PNG (store master files), export 3 sizes: 128, 256, 512.
- Scenes: master 1920x1080 or vector SVG; export responsive sizes or use SVG where possible.

Prototyping notes
- Use simple, single-file SVGs for rapid prototyping (they scale and are low weight).
- Two lightweight prototypes are added to frontend/assets/design/ as visual starting points.

---
Accessibility checklist (quick)
- [ ] aria-live for narration
- [ ] Keyboard navigable actions
- [ ] Captions for audio/TTS
- [ ] Color contrast verification

---
Design decisions summary
- Warm palette and hand-crafted, subtle textures will help the learner feel rooted in a Nigerian village context without stereotyping.
- Layered scenes + expressions give immediate visual feedback and help teach cause–effect (you clean gutter → water clears).
- Keep motion optional and light to respect cognitive load for learners.
