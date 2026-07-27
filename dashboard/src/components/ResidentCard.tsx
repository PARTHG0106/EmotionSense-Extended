import { StatusBadge } from "./StatusBadge";
import type { ResidentStatus } from "../types";
import "./ResidentCard.css";

/**
 * Resident overview card.
 *
 * Target: a caregiver understands the resident's state in under five seconds. Name, status,
 * current activity and location only. When identity confidence is low the behavioural figures
 * are withheld rather than shown with a caveat, because a number on screen is trusted
 * regardless of the disclaimer beside it.
 */
interface Props {
  status: ResidentStatus;
  onSelect?: (residentId: string) => void;
}

function sinceLabel(since: string | null): string {
  if (!since) return "no recent data";
  const minutes = Math.round((Date.now() - new Date(since).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `for ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `for ${hours} h ${minutes % 60} min`;
}

export function ResidentCard({ status, onSelect }: Props) {
  const withheld = status.identity_state === "uncertain";
  return (
    <article className="resident">
      <header className="resident__header">
        <h2 className="resident__name">{status.display_name}</h2>
        <StatusBadge severity={status.severity} label={status.severity_label} />
      </header>

      <p className="resident__activity">
        <strong>{status.current_activity}</strong>
        {status.zone ? ` in the ${status.zone.replace(/_/g, " ")}` : ""}{" "}
        <span className="resident__since">{sinceLabel(status.since)}</span>
      </p>

      <dl className="resident__metrics">
        <div>
          <dt>Well-being</dt>
          <dd>
            {withheld || status.wellbeing_score === null ? "\u2014" : status.wellbeing_score}
          </dd>
        </div>
        <div>
          <dt>Risk</dt>
          <dd>{withheld || !status.risk_level ? "\u2014" : status.risk_level}</dd>
        </div>
        <div>
          <dt>Identity</dt>
          <dd>
            {status.identity_state === "confirmed" ? "Confirmed" : "Uncertain"}{" "}
            <span className="resident__confidence">
              {Math.round(status.identity_confidence * 100)}%
            </span>
          </dd>
        </div>
      </dl>

      {status.notes.map((note) => (
        <p className="resident__note" key={note}>
          {note}
        </p>
      ))}

      {onSelect && (
        <button
          type="button"
          className="resident__link"
          onClick={() => onSelect(status.resident_id)}
        >
          View timeline
        </button>
      )}
    </article>
  );
}
