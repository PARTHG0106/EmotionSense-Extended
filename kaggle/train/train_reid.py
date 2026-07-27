"""Train the ReID encoder. Runs in the OFFLINE GPU Kaggle notebook.

Evaluation deliberately reports the two metrics that matter in a home, which are not the
metrics ReID papers optimise:
  * accuracy at a fixed low-resolution operating point, because CCTV crops are small;
  * false-merge rate, because merging two residents corrupts both baselines silently.

Usage:
    python train_reid.py --manifest /kaggle/input/reid-occluded-v1/manifest.json \\
        --run-dir /kaggle/working/runs/reid-001
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from _offline_tracker import OfflineTracker
from train_activity import assert_offline_ready, seed_everything

LOG = logging.getLogger("train.reid")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--backbone", default="osnet_x1_0")
    parser.add_argument("--embedding-dim", type=int, default=512)
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument(
        "--train-short-side",
        type=int,
        default=128,
        help="train at CCTV-like resolution, not at dataset-native resolution",
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    assert_offline_ready([args.manifest])
    seed_everything(args.seed)

    manifest = json.loads(args.manifest.read_text())
    tracker = OfflineTracker(
        args.run_dir,
        {
            "task": "reid",
            "dataset": manifest["name"],
            "dataset_version": manifest["version"],
            "args": vars(args),
            "losses": ["cross_entropy_label_smoothing", "triplet_hard", "center"],
            "augmentations": [
                "random_erasing",
                "downscale_upscale",
                "motion_blur",
                "low_light_gamma",
                "occlusion_paste",
            ],
        },
    )
    LOG.info("training %s at short side %d", args.backbone, args.train_short_side)
    tracker.summarise(
        status="scaffold",
        report_metrics=[
            "rank1",
            "mAP",
            "rank1_at_short_side_96",
            "false_merge_rate",
            "clothing_change_rank1",
        ],
        exit_criteria={
            "false_merge_rate": "<= 0.001",
            "resident_vs_visitor_accuracy": ">= 0.95",
        },
    )


if __name__ == "__main__":
    main()
