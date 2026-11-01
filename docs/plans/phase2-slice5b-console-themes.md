# Phase 2 · Slice 5b — "Holo-Lab" console: white, futuristic, animated, five themes + your colour

Status: IN PROGRESS · 2026-11-01 · ships together with slice 5 (owner merges both)

## Owner ask (verbatim intent)
"The design doesn't look good at all … highly futuristic with moving elements, animations
everywhere. The background should be white with shadow effects and animations … a few themes
for the entire portal … related to technology, take references from the Iron Man series …
the colour selection can also be given to the user."

## Research → principles
| Source | What we take |
|---|---|
| Film screen-graphics designers (Jayse Hansen on the Avengers/Iron Man HUDs; Cantina Creative, Iron Man 3) | Layered depth (several planes at different speeds/line weights); "pattern first, detail second" — readable at a glance; motion tied to the user's own gestures; holographic light (glow, flare, scan) rather than flat panels; slightly ahead of today, never arbitrary. Film UIs only serve a story; ours must work every time, so content always wins over decoration. |
| NN/g on glassmorphism | Translucency sparingly, over simple backgrounds; strong blur; check contrast against what is actually behind; let users reduce transparency. → on white we use *frosted white* panels (≥ 82 % opaque) with crisp accent strokes, not see-through glass. |
| WCAG 2.2 (via ezud.com summary) | 2.2.2 Pause/Stop/Hide: ambient motion > 5 s needs a control → **Motion: Full / Calm / Off** switch. 2.3.1: never flash ≥ 3 Hz. 2.3.3: interaction-triggered motion can be turned off. Vestibular triggers to avoid: parallax, big zooms, spinning large areas, bounce. Safe: fades, colour, small scale (≤ 1.05). |
| OKLCH / color-mix guides | Theme = a handful of CSS custom properties; tints/shades via `color-mix()`; the owner's chosen colour is contrast-checked in JS and darkened until text on white reaches 4.5 : 1. |

Intellectual property: themes evoke the films' *feel* (holographic workshop, red-and-gold, nanotech,
stealth silver, power-core glow) with original names and original shapes. No Marvel names, logos,
helmet, character or the specific reactor emblem.

## Design system
**Surface.** White page (#FFFFFF → #F4F7FB vignette). Cards are frosted white with layered soft
shadows (ambient + key + accent-tinted glow on hover), 1 px accent hairline, HUD corner brackets.
**Type.** Self-hosted, OFL: *Orbitron* (wordmark, big numbers), *Rajdhani* (HUD labels, chips,
section titles, uppercase + tracking); body text stays the system UI font for reading comfort.
**Signature element.** The *Core*: an original animated emblem — three concentric rings with
tick marks rotating at different speeds, a breathing centre glow. Idle = slow; thinking = faster
+ pulse; approval waiting = amber halo. Replaces the old orb everywhere.

### Motion map (every motion has a job)
| Where | Motion | Job | Reduced/Off |
|---|---|---|---|
| Background canvas | theme-specific field (below), ≤ 30 fps, ≤ 80 particles, pauses when tab hidden | ambience, depth | static grid |
| Scan line | thin accent line sweeps the page every ~9 s | "system alive" | none |
| Page load | panels "assemble": stagger fade + 8 px rise + corner brackets draw in | orientation | fade only |
| Core | rings rotate; speeds up + pulses while JARVIS thinks | system state | static |
| JARVIS reply | "materialise": scan-reveal (clip-path) + fade | new content | fade |
| Owner message | slides in from right 12 px + fade | feedback | fade |
| Typing | 5-bar waveform | progress | dots |
| Composer | rotating conic-gradient border on focus; send = ripple | affordance | static border |
| Buttons/cards | lift 2 px + shadow bloom + sheen sweep on hover | affordance | colour only |
| Approval card | amber glow breathing 1.8 s (never flashing) | needs you | static amber |
| Toolbar | live clock + "ONLINE" status ticker | status | static |
| Theme switch | 400 ms cross-fade of tokens | continuity | instant |

### Five themes (all on white)
| Theme | Feels like | Accent / secondary | Background field |
|---|---|---|---|
| **Workshop** (default) | the garage's holographic workbench | holo blue `#0A84FF` / cyan `#00C2E0` | blueprint grid + drifting data motes joined by faint lines |
| **Hot Rod** | red-and-gold armour | crimson `#C8102E` / gold `#D4A017` | diagonal metallic light sweeps + sparks |
| **Nanotech** | nano-particles forming a suit | graphite `#20262E` / gold `#C9A227` | particles that flow and briefly assemble into hex cells |
| **Stealth** | silver prototype, calm | steel `#4A5868` / silver `#9AA8B8` | sparse slow grid, no particles (calmest) |
| **Reactor** | power-core glow | electric `#1E6BFF` / ice `#5FD4FF` | concentric pulse rings radiating from the Core |

**Your colour.** Theme menu offers 10 preset swatches + a free colour picker. The chosen colour
replaces the theme accent; the secondary is derived; text-on-white and text-on-accent are
contrast-checked (WCAG AA) and adjusted automatically. "Reset to theme colour" restores it.
Choices (theme, colour, motion) are remembered on this device.

## Usability checklist
- Reading first: every message sits on ≥ 82 % opaque white; decorative motion stays ≤ 10 %
  opacity and never runs behind text at full strength.
- One primary action per area (Send; Approve). Approve stays visually dominant over Decline.
- Theme menu: keyboard-operable radio group, Esc closes, focus returns to the button.
- Phone: toolbar collapses to icons; inspector is a bottom sheet; canvas particles halved.
- Performance: transforms/opacity only for CSS motion; canvas DPR-aware, 30 fps cap, paused when
  hidden or Motion = Off.
- `prefers-reduced-motion` → defaults to Calm; `prefers-reduced-transparency` → solid cards.

## Build
`console.html` (styles + markup), `console.js` (theme engine, canvas field, Core, picker),
`static/fonts/*.woff2` served by a whitelisted route, package-data updated. No API changes.

## Verification
Playwright: each theme × desktop 1440 / phone 390, custom colour, Motion Off; zero JS errors;
automated contrast check of text tokens per theme; existing restore/delete flow still passes.
