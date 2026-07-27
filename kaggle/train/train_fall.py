"""Train and calibrate the fall model. Runs in the OFFLINE GPU Kaggle notebook.

The model is a second opinion, not the decision maker: the deployed detector is rule-first
(see src/wellbeing/activity/fall.py). What this script produces is a confidence score and,
critically, an operating threshold chosen on false alarms per resident-week rather than on
ROC-AUC. A 0.99-AUC model that cries wolf twice a day gets switched off, and then it detects
nothing at all.

Usage:
    python train_fall.py --manifest /kaggle/input/fall-lowres-v1/manifest.json \\
        --run-dir /kaggle/working/runs/fall-001
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from _offline_tracker import OfflineTracker
from train_activity import assert_offline_ready, seed_everything

LOG = logging.getLogger("train.fall")

TARGET_RECALL = 0.95
MAX_FALSE_ALARMS_PER_RESIDENT_WEEK = 1.0


def threshold_for_budget(
    scores: list[tuple[float, bool]],
    negative_hours: float,
    max_per_resident_week: float = MAX_FALSE_ALARMS_PER_RESIDENT_WEEK,
) -> tuple[float, float, float]:
    """Pick the lowest threshold that stays inside the false-alarm budget.

    Returns ``(threshold, recall, false_alarms_per_resident_week)``. Sweeping the threshold
    against a real budget is the only honest way to report fall performance: precision on a
    balanced test set says nothing about a home where falls are vanishingly rare.
    """
    if negative_hours <= 0:
        raise ValueError("negative_hours must be positive to compute an alarm rate")
    weeks = negative_hours / (24 * 7)
    positives = [s for s, y in scores if y]
    negatives = [s for s, y in scores if not y]
    if not positives:
        raise ValueError("no positive samples")

    best = (1.0, 0.0, 0.0)
    for candidate in sorted({round(s, 3) for s, _ in scores}):
        recall = sum(1 for s in positives if s >= candidate) / len(positives)
        false_per_week = sum(1 for s in negatives if s >= candidate) / weeks
        if false_per_week <= max_per_resident_week and recall >= best[1]:
            best = (candidate, recall, false_per_week)
    return best


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--clip-frames", type=int, default=32)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    assert_offline_ready([args.manifest])
    seed_everything(args.seed)

    manifest = json.loads(args.manifest.read_text())
    tracker = OfflineTracker(
        args.run_dir,
        {
            "task": "fall_confirmation",
            "dataset": manifest["name"],
            "dataset_version": manifest["version"],
            "role": "second opinion to the deployed kinematic rules",
            "args": vars(args),
            "hard_negatives": [
                "sitting_down_quickly",
                "lying_on_sofa",
                "bending_to_pick_up",
                "kneeling",
                "pet_or_object_motion",
            ],
        },
    )
    LOG.info(
        "selection: highest recall subject to <= %.1f false alarms/resident-week",
        MAX_FALSE_ALARMS_PER_RESIDENT_WEEK,
    )
    tracker.summarise(
        status="scaffold",
        target_recall=TARGET_RECALL,
        false_alarm_budget_per_resident_week=MAX_FALSE_ALARMS_PER_RESIDENT_WEEK,
        report_metrics=[
            "recall",
            "false_alarms_per_resident_week",
            "detection_latency_seconds",
            "recall_under_occlusion",
        ],
    )


if __name__ == "__main__":
    main()
