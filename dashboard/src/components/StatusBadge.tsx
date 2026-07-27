import type { Severity } from "../types";
import "./StatusBadge.css";

/**
 * Status badge.
 *
 * Colour is never the only carrier of meaning: every badge pairs a colour with a glyph and a
 * text label, so it survives colour-blindness, greyscale printing and dim ward lighting.
 */
const GLYPH: Record<Severity, string> = {
  normal: "\u25CF",
  attention: "\u25B2",
  warning: "\u25C6",
  critical: "\u2716",
};

interface Props {
  severity: Severity;
  label: string;
}

export function StatusBadge({ severity, label }: Props) {
  return (
    <span className={`badge badge--${severity}`}>
      <span className="badge__glyph" aria-hidden="true">
        {GLYPH[severity]}
      </span>
      <span className="badge__label">{label}</span>
    </span>
  );
}
