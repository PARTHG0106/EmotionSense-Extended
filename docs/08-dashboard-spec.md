# 08 - Dashboard specification

This is clinical software used by tired people mid-shift, sometimes at 3 a.m. on a tablet.
Target aesthetic: Apple Health / Linear / EHR reporting. Explicitly banned: neon gradients,
glowing borders, glassmorphism, cyberpunk styling, dark-with-cyan themes, animated "AI
thinking" effects, decorative AI illustrations, cluttered multi-series charts.

## Design tokens

```css
--surface-page:     #F8FAFA;
--surface-card:     #FFFFFF;
--border-subtle:    #E3E8E8;
--text-primary:     #16211F;
--text-secondary:   #5A6866;
--accent:           #2E6F6A;   /* muted teal, navigation and focus only */
--accent-soft:      #E8F1F0;
--status-normal:    #2F7A55;
--status-attention: #A6811F;
--status-warning:   #B4611C;
--status-critical:  #A32626;
--font: Inter, "SF Pro Text", system-ui, sans-serif;
--radius: 10px;
--shadow-card: 0 1px 2px rgba(22,33,31,.06);
```

One accent colour, four status colours, no gradients. Motion is limited to 150 ms
opacity/position transitions. Nothing pulses or glows; the sole exception is a critical
alert, which may use one slow 2 s border fade and also announces via `role="alert"`.

## Accessibility (non-negotiable)

- Status is always colour **plus** icon **plus** text: `Normal`, `Attention`, `Warning`,
  `Critical`. A monochrome printout must stay readable.
- 4.5:1 contrast for text, 3:1 for UI boundaries; body text 15 px, never below 13 px.
- Full keyboard operation with a visible focus ring; touch targets >= 44 px.
- Optional 125% larger-type mode.

## Screen 1 - resident overview

One calm card per resident, sorted by attention required, then by name. Each card shows:
severity chip with label, current posture and zone with duration, identity confidence,
well-being score, risk level, one 12-hour activity sparkline, and two actions.

Deliberate decisions:

- **No live video thumbnails on the overview.** They invite surveillance-style watching,
  create a privacy liability, and add nothing over a text state. Video is per-incident,
  permissioned and audited.
- **Identity confidence is on the face of the card.** When identity is `unknown` or low,
  behavioural claims are greyed out, because they are not trustworthy in that state.
- One sparkline maximum per card.

## Screen 2 - resident detail

Fixed section order: Now; open alerts; day timeline (00:00-24:00, camera-outage gaps
hatched as "no data", never rendered as inactivity); routine vs baseline band; 28-day
mobility trend with the Mann-Kendall verdict in words; anomaly history as a list, not a
heatmap; caregiver notes; daily and weekly reports.

## Alert hierarchy

| Severity | Example trigger | Delivery | Human review |
| --- | --- | --- | --- |
| Normal | routine day | dashboard | no |
| Attention | 1.5-2.5 sigma on one metric | dashboard + shift digest | optional |
| Warning | >= 2.5 sigma, or two correlated metrics | dashboard + push | required |
| Critical | confirmed fall, prolonged non-response, night-time unrecovered lying | push + on-call escalation, 60 s acknowledge timer | mandatory |

An unacknowledged critical alert escalates to the next contact after 60 s and never closes
itself. Every alert card ends with one-tap `Useful / Not useful / False alarm`.

## Score presentation

Well-being is `0-100`, risk is `Low / Moderate / High`. Both are always one tap from their
breakdown (mobility, routine adherence, rest quality, social contact). A score that cannot
be decomposed will either be ignored or over-trusted.

## Frontend stack

React + TypeScript, Vite, TanStack Query, WebSocket for live deltas, Recharts with a
stripped theme, `date-fns` in resident-local time. The frontend never recomputes clinical
logic - severity and copy are server-driven. When data is stale it shows the last known
state with an explicit "data as of HH:MM" stamp instead of a spinner.
