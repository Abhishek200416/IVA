# Bespoke UI/UX Masterworks • Production Showcase

Welcome to the **Bespoke UI/UX Masterworks** repository suite engineered by **Iva**.

This directory contains **7 handcrafted web masterworks**, each engineered with an entirely unique spatial skeleton, distinct typographic identity, 5-tier adaptive responsiveness, and zero template reuse.

---

## 🚀 Quick Start: Viewing the Masterworks
To inspect the collection:
1. Open [`index.html`](index.html) in any modern browser.
2. Click **"OPEN IN NEW TAB →"** on any design card to test its interactive flow, scroll choreography, and responsive reflow.

---

## 🏛️ The Curated Masterworks Index

| # | Masterwork | Discipline & Atmosphere | Spatial Layout Skeleton & Scroll Choreography |
|---|---|---|---|
| **01** | [`01_kura_split_screen.html`](01_kura_split_screen.html) | Copenhagen & Kyoto Architecture Atelier | **50/50 Vertical Split-Screen**: Left panel remains 100vh pinned while right panel smoothly scrolls project case studies. Zero navbar, zero cards. |
| **02** | [`02_vesper_corner_hud.html`](02_vesper_corner_hud.html) | Paris Haute Couture Monograph | **4-Corner Anchored HUD**: Pinned corner coordinates frame a central stage portrait; typography blends over imagery via `mix-blend-mode: difference`. |
| **03** | [`03_somerset_broadsheet.html`](03_somerset_broadsheet.html) | 19th-Century Historical Literary Broadsheet | **3-Column Historical Broadsheet**: Rag paper texture, marginalia colophon & errata notes, drop-cap essay column, perforated subscription slip. |
| **04** | [`04_brutalist_manifesto.html`](04_brutalist_manifesto.html) | Swiss Industrial Hardware Manifesto | **Asymmetric Diagonal Grid**: Continuous running industrial ticker tape, heavy 3px solid black borders, hard 6px offset drop boxes, zero soft shadows. |
| **05** | [`05_horizon_film_lookbook.html`](05_horizon_film_lookbook.html) | 35mm Cinematography Archive | **Horizontal-First Horizon Reel**: Zero vertical scroll, mousewheel/arrow key horizontal glide, pinned vertical brand pillar with counter `[01/04]`. |
| **06** | [`06_sculptor_monograph.html`](06_sculptor_monograph.html) | Scandinavian Monolithic Sculpture | **Asymmetric Museum Monograph**: Sticky curatorial sidebar with live material toggle (Limestone / Bronze / Basalt) recalculating dimensions and weight live. |
| **07** | [`07_aurelia_apothecary.html`](07_aurelia_apothecary.html) | High-Alpine Biodynamic Botanicals | **Asymmetric Parallax Dual Stream**: Fixed 360° rotating harvest compass HUD tracking scroll position across 4 seasons; 1.4x offset parallax scroll. |

---

## 📱 5-Tier Adaptive Responsiveness
Every design natively adapts across 5 distinct viewport tiers:
1. **Mobile Handheld (320px – 640px)**: Single-column vertical stacks, touch targets $\ge 44\times 44\text{px}$, fluid font scaling with `clamp()`.
2. **Tablet / Foldable (641px – 1024px)**: 2-column asymmetric bento grids, hybrid touch/pointer ergonomics.
3. **Laptop (1025px – 1440px)**: Baseline primary canvas, full split-screens, and horizontal cinema reels.
4. **Desktop Monitor (1441px – 1920px)**: Contained max-width boundaries, 2x DPR rendering, spacious gutters.
5. **Ultra-Wide & 4K Monitoring (1921px – 3840px+)**: High-density monitoring layouts, wall-display legibility.

---

## 🛡️ Running the Quality & Anti-AI-Slop Audit
Before contributing new designs, run the automated verification script:
```bash
py -3 showcase/bespoke_masterworks/audit_masterworks.py
```
This script audits:
- **Anti-AI-Slop Index**: Confirms `0.0` violations (no cliché purple gradients, no generic 3-card rows, no empty marketing filler).
- **Asset Integrity**: Confirms all referenced photography exists and resolves.
- **Responsive Media Queries**: Confirms mobile/tablet breakpoints are present.
- **Navigation Safety**: Confirms all links in `index.html` open with `target="_blank"`.

---

## 📖 Design Charters & Guidelines
For complete design doctrine, reference:
- [`agents/IVA/docs/library/16_CREATIVE_UI_UX_DESIGN_ARCHITECTURE.md`](../../agents/IVA/docs/library/16_CREATIVE_UI_UX_DESIGN_ARCHITECTURE.md)
  - Section 9: Banned Generic Corporate & Tech Archetypes
  - Section 10: The Authoritative 5-Phase Production Design Protocol
  - Section 11: Client Request Ingestion & Counter Protocol
  - Section 12: Universal Mandatory UI Mandate & 6 Quality Pillars
  - Section 13: 5-Tier Adaptive Responsiveness Architecture
