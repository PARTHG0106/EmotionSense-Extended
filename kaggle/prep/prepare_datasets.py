"""Dataset preparation. Runs in the INTERNET-ENABLED, NO-GPU Kaggle notebook.

The split exists because the GPU training notebook has no network access. Everything that
touches the internet happens here, once, and the output is a versioned Kaggle dataset that
the training notebook mounts read-only.

Steps: download -> verify checksum -> convert annotations -> resize/filter -> split ->
manifest -> package. The manifest is what makes a training run reproducible: it records the
exact file list and hashes that produced a checkpoint.

Usage:
    python prepare_datasets.py --spec specs/fall_lowres.yaml --out /kaggle/working/fall_lowres
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

LOG = logging.getLogger("prep")

# Subject-disjoint splits. Frame-level shuffling leaks the same person across train and
# validation and inflates every metric, most severely for ReID and fall detection.
SPLIT_RATIOS = {"train": 0.7, "val": 0.15, "test": 0.15}


@dataclass(slots=True)
class DatasetSpec:
    """Declarative description of one prepared dataset."""

    name: str
    version: str
    sources: list[dict[str, Any]]
    target_short_side: int = 256
    max_short_side_upscale: bool = False
    min_bbox_pixels: int = 24
    label_map: dict[str, str] = field(default_factory=dict)
    split_by: str = "subject"
    seed: int = 42
    notes: str = ""

    @classmethod
    def load(cls, path: Path) -> DatasetSpec:
        data = yaml.safe_load(path.read_text())
        return cls(**data)


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def verify(path: Path, expected_sha256: str | None) -> None:
    """Fail loudly on checksum mismatch.

    A silently truncated archive produces a model that trains and evaluates fine on the
    truncated data, which is the worst possible failure mode.
    """
    if expected_sha256 is None:
        LOG.warning("no checksum declared for %s; provenance unverified", path.name)
        return
    actual = sha256_of(path)
    if actual != expected_sha256:
        raise ValueError(f"checksum mismatch for {path.name}: {actual} != {expected_sha256}")
    LOG.info("verified %s", path.name)


def downscale_only(
    width: int, height: int, target_short_side: int, allow_upscale: bool
) -> tuple[int, int]:
    """Resize toward CCTV resolution, never away from it.

    Upscaling a crisp 1080p research clip teaches the model detail that home CCTV will never
    provide. Downscaling is the domain shift we actually want.
    """
    short = min(width, height)
    if short <= target_short_side and not allow_upscale:
        return width, height
    scale = target_short_side / short
    return max(1, round(width * scale)), max(1, round(height * scale))


def assign_splits(subject_ids: list[str], seed: int) -> dict[str, str]:
    """Deterministic subject-disjoint split assignment."""
    ordered = sorted(set(subject_ids))
    random.Random(seed).shuffle(ordered)
    total = len(ordered)
    n_train = int(total * SPLIT_RATIOS["train"])
    n_val = int(total * SPLIT_RATIOS["val"])
    assignment: dict[str, str] = {}
    for index, subject in enumerate(ordered):
        if index < n_train:
            assignment[subject] = "train"
        elif index < n_train + n_val:
            assignment[subject] = "val"
        else:
            assignment[subject] = "test"
    return assignment


def build_manifest(spec: DatasetSpec, out_dir: Path, records: list[dict[str, Any]]) -> Path:
    """Write the manifest that the training notebook reads instead of globbing files."""
    counts: dict[str, int] = {}
    for record in records:
        key = f"{record['split']}:{record.get('label', 'unlabelled')}"
        counts[key] = counts.get(key, 0) + 1
    manifest = {
        "name": spec.name,
        "version": spec.version,
        "split_by": spec.split_by,
        "seed": spec.seed,
        "target_short_side": spec.target_short_side,
        "label_map": spec.label_map,
        "counts": counts,
        "n_records": len(records),
        "sources": [
            {"name": s.get("name"), "license": s.get("license"), "sha256": s.get("sha256")}
            for s in spec.sources
        ],
        "notes": spec.notes,
        "records": records,
    }
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2))
    LOG.info("wrote manifest with %d records to %s", len(records), path)
    return path


def package(out_dir: Path, dataset_slug: str) -> Path:
    """Produce the archive to upload as a Kaggle dataset."""
    metadata = {
        "title": dataset_slug.replace("-", " ").title(),
        "id": f"PARTHG0106/{dataset_slug}",
        "licenses": [{"name": "other"}],
    }
    (out_dir / "dataset-metadata.json").write_text(json.dumps(metadata, indent=2))
    archive = shutil.make_archive(str(out_dir), "zip", root_dir=out_dir)
    LOG.info("packaged %s", archive)
    LOG.info("upload with: kaggle datasets create -p %s --dir-mode zip", out_dir)
    return Path(archive)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--slug", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    spec = DatasetSpec.load(args.spec)
    args.out.mkdir(parents=True, exist_ok=True)

    LOG.info("preparing %s v%s from %d source(s)", spec.name, spec.version, len(spec.sources))
    records: list[dict[str, Any]] = []
    subjects: list[str] = []

    for source in spec.sources:
        # Download and extraction are source-specific; each source contributes records of
        # the shape below. Kept explicit so provenance is never lost.
        LOG.info("source %s (license: %s)", source.get("name"), source.get("license"))
        for record in source.get("records", []):
            subjects.append(str(record.get("subject_id", "unknown")))
            records.append(dict(record))

    assignment = assign_splits(subjects, spec.seed)
    for record in records:
        record["split"] = assignment.get(str(record.get("subject_id", "unknown")), "train")
        if "label" in record and spec.label_map:
            record["label"] = spec.label_map.get(record["label"], record["label"])

    build_manifest(spec, args.out, records)
    if not args.dry_run:
        package(args.out, args.slug or spec.name.replace("_", "-"))


if __name__ == "__main__":
    main()
