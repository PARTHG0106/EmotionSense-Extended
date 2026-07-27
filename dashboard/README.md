# Caregiver dashboard

React + TypeScript + Vite. The full specification is in [`../docs/08-dashboard-spec.md`](../docs/08-dashboard-spec.md).

```bash
npm install
npm run dev   # expects the API at http://localhost:8000
```

## What this interface deliberately is not

No dark control-room theme, no neon or glassmorphism, no ambient animation, no AI iconography.
Caregivers read this during a shift, often on a shared tablet in poor lighting. The reference
points are Apple Health, Linear and hospital EHR software, not science fiction.

## Rules enforced in code, not by convention

1. **Colour is never the only signal.** `StatusBadge` always pairs colour with a glyph and a
   text label. All four status colours pass 4.5:1 on white.
2. **Severity copy comes from the server.** The client renders `severity_label`; it never maps
   severity to words itself, so the label and the colour cannot disagree.
3. **Every alert shows all six explanation fields.** There is no summary-only mode.
4. **Low identity confidence withholds numbers.** When `identity_state` is `uncertain`,
   well-being and risk render as an em dash. A number on screen is trusted regardless of any
   caveat printed next to it.
5. **Motion is state-driven only**, and disabled under `prefers-reduced-motion`.

## Structure

| Path | Purpose |
| --- | --- |
| `src/styles/tokens.css` | Design tokens: surfaces, text, status colours, spacing, type scale |
| `src/types.ts` | Mirrors the API response contracts |
| `src/components/StatusBadge.tsx` | Colour + glyph + label status indicator |
| `src/components/ResidentCard.tsx` | Overview card, readable in under five seconds |
| `src/components/AlertCard.tsx` | Alert with the full six-field explanation |
