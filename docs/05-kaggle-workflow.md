# 05 - Kaggle training workflow

Constraints: RTX PRO 6000 available, **internet disabled in the GPU notebook**, datasets
must already exist as Kaggle Datasets, notebooks must be reproducible offline.

## Notebook A - `kaggle/prep/prepare_datasets.py` (CPU, internet ON)

1. Download sources; check licenses. Gated datasets (Toyota Smarthome, MSMT17, Human3.6M)
   require request forms - start these first, approvals take days to weeks.
2. Verify: file counts, checksums, corrupt-frame scan, label-range validation.
3. Convert to one canonical format per task: COCO JSON for detection and pose, MOT-txt for
   tracking, Market-1501 folder layout for ReID, and a single `clips.parquet` manifest
   (`clip_id, path, label, subject, camera, split, fps, resolution`) for action and fall.
4. Pre-extract frames at a fixed short side and pre-compute degraded variants, writing
   shards so the GPU notebook never spends time on video decoding.
5. Split by **subject and camera**, never randomly by clip. Random splits leak identity and
   inflate every metric in this domain.
6. Emit `dataset_card.md` and `manifest.json`: source, version, license, checksum, split
   policy, class map.
7. Also package a **weights dataset** containing every pretrained checkpoint the GPU
   notebook will need, plus any wheels that are not preinstalled.
8. Push with `kaggle datasets create` / `version`, one dataset per task, semver.

## Notebook B - `kaggle/train/train_<task>.py` (GPU, internet OFF)

- Attach prepped datasets + the weights dataset. No `torch.hub`, no `from_pretrained`
  network call, no `pip install` from PyPI.
- `seed_everything(42)` across torch, numpy, random, with deterministic cuDNN.
- bf16 mixed precision, gradient accumulation to reach the effective batch size, cosine
  schedule with warmup, EMA weights, per-epoch checkpoints plus a best-metric checkpoint.
- **Offline experiment tracking**: append one JSON line per epoch to
  `runs/<task>/<run_id>/metrics.jsonl` and write `config.resolved.yaml`, recording git SHA,
  config hash, dataset version, seed, hardware and wall time. Zip `runs/` as notebook
  output and push it as a dataset version so history survives session teardown.
- A run without dataset version, seed and config hash is not an experiment, it is an
  anecdote. `kaggle/train/_offline_tracker.py` enforces this.

## Realistic single-GPU budget

Detection fine-tune ~6 h; ReID ~8 h per protocol; pose fine-tune ~10 h; VideoMAE ADL ~20 h;
ST-GCN fall ~3 h; behaviour models under 1 h.

Sequence in roadmap order. Do not train ADL before identity works, because ADL labels are
per-resident and a broken identity layer silently mislabels the training signal.
