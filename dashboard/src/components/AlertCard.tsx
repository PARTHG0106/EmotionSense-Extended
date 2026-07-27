import { StatusBadge } from "./StatusBadge";
import type { AlertView } from "../types";
import "./AlertCard.css";

/**
 * Alert card.
 *
 * The six explanation fields are always rendered. There is deliberately no collapsed
 * "summary only" mode: an alert a caregiver cannot interrogate is an alert they will learn to
 * dismiss. "Why flagged" and "vs baseline" are the two fields that earn trust, so they are
 * always visible rather than hidden behind a disclosure.
 */
interface Props {
  alert: AlertView;
  onAcknowledge?: (alertId: string) => void;
}

export function AlertCard({ alert, onAcknowledge }: Props) {
  const { explanation } = alert;
  return (
    <article
      className={`alert alert--${alert.severity}`}
      aria-labelledby={`alert-${alert.alert_id}-title`}
    >
      <header className="alert__header">
        <StatusBadge severity={alert.severity} label={alert.severity_label} />
        <time className="alert__time" dateTime={alert.ts}>
          {explanation.when}
        </time>
      </header>

      <h3 className="alert__title" id={`alert-${alert.alert_id}-title`}>
        {explanation.what}
      </h3>

      <dl className="alert__fields">
        <dt>Why this was flagged</dt>
        <dd>{explanation.why_flagged}</dd>
        <dt>Compared with their normal</dt>
        <dd>{explanation.baseline_delta}</dd>
        <dt>Confidence</dt>
        <dd>{explanation.confidence}</dd>
      </dl>

      <p className="alert__next">
        <strong>What to check next:</strong> {explanation.check_next}
      </p>

      {alert.requires_human_review && (
        <p className="alert__review">
          Needs a person to confirm. This is a signal to check, not a diagnosis.
        </p>
      )}

      <footer className="alert__footer">
        {onAcknowledge && (
          <button
            type="button"
            className="alert__ack"
            onClick={() => onAcknowledge(alert.alert_id)}
          >
            Acknowledge
          </button>
        )}
        <span className="alert__evidence">
          {alert.evidence_event_ids.length} supporting event
          {alert.evidence_event_ids.length === 1 ? "" : "s"}
        </span>
      </footer>
    </article>
  );
}
