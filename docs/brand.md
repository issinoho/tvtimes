# tvtimes — brand

## Name

Always lowercase: **tvtimes**. Never "TVTimes" or "TV Times".

## Logo

A custom lockup built from an openly-licensed base glyph:

- Base icon: [Iconoir](https://iconoir.com) (MIT) or [Lucide](https://lucide.dev)
  (ISC) — `tv` / `clapperboard`.
- **Mark**: a rounded-rect "screen" with a faint horizontal scanline and a play
  triangle, filled with the brand gradient (`--grad-brand`).
- **Wordmark**: "tvtimes" set in **Space Grotesk** (SIL OFL), weight 500,
  `-0.01em` tracking.

Assets live in `frontend/src/assets/brand/`:

| File | Use |
|------|-----|
| `logo-mark.svg` | square mark, app icon, favicon source |
| `logo-lockup.svg` | mark + wordmark, horizontal, for headers |
| `favicon.svg` / `favicon-32.png` / `apple-touch-icon.png` | tabs / installs |

## Colour wash — "twilight aurora"

The signature look: a large, soft, blurred gradient behind the guide over a
near-black ground, with a faint film-grain texture — "a set-top box glowing in a
dark living room".

### Dark theme (default)

| Token | Value | Role |
|-------|-------|------|
| `--bg` | `#0B0713` | app canvas |
| `--bg-raised` | `#150C24` | cards, guide rows |
| `--bg-overlay` | `#1E1233` | popovers, sheets |
| `--brand-indigo` | `#1B0A3D` | gradient stop 0 |
| `--brand-violet` | `#6D28D9` | gradient stop 1 / primary action |
| `--brand-pink` | `#DB2777` | gradient stop 2 / focus, "now" line |
| `--brand-amber` | `#F59E0B` | accent, ratings star, live badge |
| `--text` | `#F4EEFF` | primary text |
| `--text-dim` | `#A99FC4` | secondary text |
| `--line` | `#2C2140` | borders, grid lines |

`--grad-brand: linear-gradient(120deg, #1B0A3D 0%, #6D28D9 45%, #DB2777 100%)`

`--wash`: a `radial-gradient(1200px 800px at 15% -10%, rgba(109,40,217,.35),
transparent 60%)` layered with `radial-gradient(1000px 700px at 110% 10%,
rgba(219,39,119,.28), transparent 55%)`, blurred, behind everything; grain is a
tiled SVG `feTurbulence` PNG at ~4% opacity.

### Light theme

Same hues, raised lightness, off-white ground:

| Token | Value |
|-------|-------|
| `--bg` | `#F7F4FB` |
| `--bg-raised` | `#FFFFFF` |
| `--bg-overlay` | `#FFFFFF` |
| `--brand-violet` | `#6D28D9` |
| `--brand-pink` | `#C81E63` |
| `--brand-amber` | `#B4740A` |
| `--text` | `#1B1230` |
| `--text-dim` | `#5B5175` |
| `--line` | `#E4DCF0` |

Theme is chosen by `prefers-color-scheme`, overridable with a
`data-theme="light|dark"` attribute on `<html>`. All values are CSS custom
properties in `frontend/src/styles/theme.css`.

## Genre palette (guide cells & chips)

Fixed, accessible categorical set — assign by primary EPG/TMDB genre, fall back
to `--genre-default`. Each has a matching `-fg` text colour that meets WCAG AA on
its fill in both themes.

| Genre | Fill (dark) |
|-------|-------------|
| Film / Movie | `#7C3AED` |
| Sport | `#0EA5E9` |
| News | `#EF4444` |
| Kids | `#F59E0B` |
| Documentary | `#10B981` |
| Entertainment | `#EC4899` |
| Drama / Series | `#8B5CF6` |
| Music | `#F43F5E` |
| default | `#4B5563` |

## Motion

Framer Motion. Hero backdrop cross-fades in over 240ms; the guide "now" line
pulses subtly. All motion respects `prefers-reduced-motion: reduce`.

## TMDB attribution

Where TMDB data is shown, display: *"This product uses the TMDB API but is not
endorsed or certified by TMDB."* plus the TMDB logo, per their terms of use.
