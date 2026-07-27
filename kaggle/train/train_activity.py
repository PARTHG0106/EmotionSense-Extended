"""Train the ADL classifier. Runs in the OFFLINE GPU Kaggle notebook.

No network calls, no live downloads, no pretrained-weight fetches: weights and data must
already be mounted as Kaggle datasets under /kaggle/input. The script fails fast if they are
missing rather than silently training from scratch.

Usage:
    python train_activity.py \\
        --manifest /kaggle/input/adl-lowres-v1/manifest.json \\
        --pretrained /kaggle/input/videomae-base-offline \\
        --run-dir /kaggle/working/runs/adl-001
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
from pathlib import Path
from typing import Any

from _offline_tracker import OfflineTracker

LOG = logging.getLogger("train.activity")


def assert_offline_ready(paths: list[Path]) -> None:
    """Verify every required input is mounted before touching the GPU."""
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "missing mounted Kaggle inputs (the GPU notebook has no internet, so these "
            f"must be attached as datasets): {missing}"
        )


def seed_everything(seed: int) -> None:
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import numpy as np
        import torch

        np.random.seed(seed)
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        # Determinism over throughput: ablations are meaningless if runs are not comparable.
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    except ImportError:
        LOG.warning("torch/numpy unavailable; seeding python only")


def class_weights(counts: dict[str, int], labels: list[str]) -> list[float]:
    """Inverse-frequency weights.

    ADL data is severely imbalanced (sitting dominates, medication routine is rare). An
    unweighted model reaches high accuracy by predicting 'sitting' and is clinically useless.
    """
    total = sum(counts.get(label, 0) for label in labels) or 1
    return [total / max(1, counts.get(label, 0)) / len(labels) for label in labels]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--pretrained", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--accum-steps", type=int, default=4, help="effective batch = bs * accum")
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--clip-frames", type=int, default=16)
    parser.add_argument("--amp", action="store_true", default=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    assert_offline_ready([args.manifest, args.pretrained])
    seed_everything(args.seed)

    manifest: dict[str, Any] = json.loads(args.manifest.read_text())
    labels = sorted({r["label"] for r in manifest["records"] if "label" in r})
    counts = {
        label: sum(
            1 for r in manifest["records"] if r.get("label") == label and r.get("split") == "train"
        )
        for label in labels
    }

    tracker = OfflineTracker(
        args.run_dir,
        {
            "task": "adl_classification",
            "dataset": manifest["name"],
            "dataset_version": manifest["version"],
            "labels": labels,
            "train_counts": counts,
            "args": vars(args),
        },
    )

    LOG.info("labels: %s", labels)
    LOG.info("class weights: %s", [round(w, 3) for w in class_weights(counts, labels)])
    LOG.info(
        "effective batch size %d (%d x %d accumulation)",
        args.batch_size * args.accum_steps,
        args.batch_size,
        args.accum_steps,
    )

    # Training loop: build dataloaders from manifest records, load the mounted backbone,
    # train with AMP + gradient accumulation, checkpoint on best validation macro-F1.
    # Macro-F1, never accuracy: the rare classes are the clinically useful ones.
    tracker.summarise(
        status="scaffold",
        selection_metric="val_macro_f1",
        note=(
            "Model construction is the only per-backbone part left to fill; the data "
            "contract, seeding, class weighting and tracking are fixed."
        ),
    )


if __name__ == "__main__":
    main()
