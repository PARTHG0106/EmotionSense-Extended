export type Severity = "normal" | "attention" | "warning" | "critical";

/** Mirrors the six-field explanation contract. The UI cannot render an alert without it. */
export interface Explanation {
  what: string;
  when: string;
  why_flagged: string;
  baseline_delta: string;
  confidence: string;
  check_next: string;
}

export interface AlertView {
  alert_id: string;
  resident_id: string;
  ts: string;
  severity: Severity;
  /** Server-driven so the label and the colour can never disagree. */
  severity_label: string;
  kind: string;
  explanation: Explanation;
  explanation_lines: string[];
  prose: string | null;
  confidence: number;
  requires_human_review: boolean;
  suppressed_reason: string | null;
  evidence_event_ids: string[];
}

export interface ResidentStatus {
  resident_id: string;
  display_name: string;
  severity: Severity;
  severity_label: string;
  current_activity: string;
  zone: string | null;
  since: string | null;
  identity_confidence: number;
  identity_state: "confirmed" | "uncertain";
  wellbeing_score: number | null;
  risk_level: string | null;
  baseline_forming: boolean;
  data_as_of: string;
  notes: string[];
}
