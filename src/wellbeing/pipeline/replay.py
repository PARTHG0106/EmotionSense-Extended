"""Deterministic replay of a stored perception trace.

This module exists so that the entire L2-L4 path can be re-run, bit for bit, without a
camera, a GPU, or a model. A trace is a JSON Lines file where each line is one
:class:`~wellbeing.contracts.perception.PerceptionFrame`.

Why this matters more than it first appears:

* **Incident review.** When a caregiver disputes an alert, the stored trace reproduces the
  exact events, assessment and explanation that were shown at the time.
* **Regression safety.** Changing a fall rule or a baseline window is otherwise unfalsifiable.
  Replaying yesterday's traces shows precisely which alerts appear or disappear.
* **Privacy.** A trace holds geometry and identity references, not pixels, so it can be kept
  for the 30-day keypoint retention window without storing raw video.

A replay never calls the perception layer, so a trace recorded on one model version stays
replayable after that model is replaced. ``model_versions`` travels on each frame precisely
so a later reviewer can tell which detector produced it.

Usage::

    python -m wellbeing.pipeline.replay tests/fixtures/trace_day.jsonl --review
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from wellbeing.config import AppConfig, load_config
from wellbeing.contracts.activity import ActivityEvent
from wellbeing.contracts.alerts import Alert
from wellbeing.contracts.perception import PerceptionFrame
from wellbeing.pipeline.orchestrator import DayReview, Pipeline


class TraceFormatError(ValueError):
    """Raised when a trace line is not a valid perception frame.

    Carries the line number, because a trace is typically thousands of lines long and a
    bare validation error is close to useless for finding the bad row.
    """

    def __init__(self, path: Path, line_number: int, detail: str) -> None:
        super().__init__(f"{path}:{line_number}: {detail}")
        self.path = path
        self.line_number = line_number


def read_trace(path: str | Path, *, strict: bool = True) -> Iterator[PerceptionFrame]:
    """Stream frames from a JSON Lines trace.

    Yields lazily so that a multi-day trace does not have to fit in memory.

    Args:
        path: Trace file. Blank lines and ``#`` comment lines are skipped.
        strict: When true, an invalid line raises. When false, it is reported to stderr and
            skipped, which is what you want when salvaging a trace truncated by a crash.
    """
    trace_path = Path(path)
    with trace_path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                yield PerceptionFrame.model_validate_json(line)
            except Exception as error:  # noqa: BLE001 - re-raised with position context
                failure = TraceFormatError(trace_path, line_number, str(error))
                if strict:
                    raise failure from error
                print(f"skipping {failure}", file=sys.stderr)


def write_trace(path: str | Path, frames: list[PerceptionFrame]) -> Path:
    """Write frames as JSON Lines. Used by capture tooling and by test fixtures."""
    trace_path = Path(path)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_path.open("w", encoding="utf-8") as handle:
        for frame in frames:
            handle.write(frame.model_dump_json() + "\n")
    return trace_path


def replay(
    path: str | Path,
    config: AppConfig | None = None,
    *,
    strict: bool = True,
) -> tuple[Pipeline, list[ActivityEvent], list[Alert]]:
    """Replay a trace through the live path and return the pipeline plus its output.

    The pipeline is returned as well as the events so that the caller can run
    :meth:`Pipeline.review_day` afterwards against the same accumulated event log.
    """
    pipeline = Pipeline(config or load_config())
    events, alerts = pipeline.process_frames(read_trace(path, strict=strict))
    return pipeline, events, alerts


def review_all_subjects(
    pipeline: Pipeline, events: list[ActivityEvent], day: date | None = None
) -> list[DayReview]:
    """Run the nightly review for every resident seen in the trace.

    Visitors are skipped deliberately: they have no baseline, and building one for a person
    who is not the subject of care would be both useless and a privacy violation.
    """
    if not events:
        return []
    target = day or min(e.window.start.date() for e in events)
    subjects = sorted(
        {e.subject_id for e in events if e.subject_id.startswith("resident")}
        or {e.subject_id for e in events}
    )
    return [pipeline.review_day(subject, target) for subject in subjects]


def _print_events(events: list[ActivityEvent]) -> None:
    print(f"\n{len(events)} activity events")
    print("-" * 78)
    for event in events:
        print(
            f"{event.window.start:%H:%M:%S}  {event.label.value:<22}"
            f"{event.window.duration_seconds:7.1f}s  conf={event.confidence:.2f}"
            f"  id={event.identity_confidence:.2f}  via {event.source.value}"
        )


def _print_alerts(alerts: list[Alert]) -> None:
    print(f"\n{len(alerts)} alerts")
    print("-" * 78)
    for alert in alerts:
        print(f"[{alert.severity.value.upper()}] {alert.kind.value}  confidence={alert.confidence:.2f}")
        for line in alert.explanation.as_lines():
            print(f"    {line}")
        if alert.suppressed_reason:
            print(f"    SUPPRESSED: {alert.suppressed_reason}")
        # An incomplete explanation is a release blocker, so it is surfaced loudly here
        # rather than left for someone to notice in the dashboard.
        if not alert.explanation.is_complete:
            print(f"    INCOMPLETE EXPLANATION: missing {alert.explanation.missing_fields}")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wellbeing.pipeline.replay",
        description="Replay a stored perception trace through the activity, behaviour and reasoning layers.",
    )
    parser.add_argument("trace", help="JSON Lines file of PerceptionFrame records")
    parser.add_argument("--config", default=None, help="config YAML overlay (defaults to configs/default.yaml)")
    parser.add_argument("--review", action="store_true", help="also run the nightly behaviour review")
    parser.add_argument("--day", default=None, help="ISO date to review (defaults to the trace's first day)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of a report")
    parser.add_argument("--lenient", action="store_true", help="skip malformed lines instead of failing")
    args = parser.parse_args(argv)

    config = load_config(args.config) if args.config else load_config()
    pipeline, events, alerts = replay(args.trace, config, strict=not args.lenient)

    reviews: list[DayReview] = []
    if args.review:
        day = date.fromisoformat(args.day) if args.day else None
        reviews = review_all_subjects(pipeline, events, day)
        for review in reviews:
            alerts.extend(review.alerts)

    if args.json:
        print(
            json.dumps(
                {
                    "events": [json.loads(e.model_dump_json()) for e in events],
                    "alerts": [json.loads(a.model_dump_json()) for a in alerts],
                    "reviews": [
                        {
                            "subject_id": r.subject_id,
                            "day": r.day.isoformat(),
                            "anomalies": len(r.anomalies),
                            "trends": [t.statement for t in r.trends],
                        }
                        for r in reviews
                    ],
                },
                indent=2,
            )
        )
        return 0

    _print_events(events)
    _print_alerts(alerts)
    for review in reviews:
        print(f"review {review.subject_id} {review.day}: "
              f"{len(review.anomalies)} anomalies, {len(review.trends)} trends, "
              f"{len(review.actionable_alerts)} actionable alerts")

    # Non-zero exit if any alert cannot be fully explained: this makes replay usable as a CI gate.
    incomplete = [a for a in alerts if not a.explanation.is_complete]
    if incomplete:
        print(f"\nFAIL: {len(incomplete)} alert(s) with incomplete explanations", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
