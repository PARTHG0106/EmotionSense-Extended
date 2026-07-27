# Kaggle notebooks

Five notebooks, run in order. They wrap the scripts in `kaggle/prep/` and `kaggle/train/`
rather than duplicating them, so notebook and CLI runs are guaranteed to behave identically.

| # | Notebook | Internet | Accelerator | Produces |
| --- | --- | --- | --- | --- |
| 01 | `01_prepare_datasets.ipynb` | **On** | None | A versioned Kaggle dataset + bundled repo source |
| 02 | `02_train_activity.ipynb` | **Off** | GPU | ADL classifier checkpoint + macro-F1 report |
| 03 | `03_train_reid.ipynb` | **Off** | GPU | ReID encoder + false-merge report |
| 04 | `04_train_fall.ipynb` | **Off** | GPU | Fall scorer + threshold at the false-alarm budget |
| 05 | `05_evaluate_pipeline.ipynb` | Optional | None | End-to-end smoke test + explanation audit |

## Why the split exists

The GPU notebook has **no network access**. Every download, checksum, annotation conversion
and resize therefore happens once in notebook 01, whose output is a Kaggle dataset that the
GPU notebooks mount read-only. A training notebook that tries to `pip install` or fetch
pretrained weights will fail at runtime, so notebooks 02–04 assert their inputs are mounted
*before* they touch the GPU.

Notebook 01 also bundles the repository's `src/` tree into the output dataset under `code/`.
That is how the offline notebooks import `wellbeing` without a clone.

## Non-obvious conventions these notebooks enforce

- **Subject-disjoint splits.** Frame-level shuffling leaks the same person across train and
  validation. It inflates every metric, catastrophically so for ReID and falls.
- **Downscale only.** Research clips are sharper than home CCTV. Upscaling teaches detail
  that will never exist at inference; downscaling is the domain shift we want.
- **Macro-F1, never accuracy.** The rare ADL classes are the clinically useful ones.
- **Fall thresholds are chosen against a false-alarm budget**, not against ROC-AUC.
- **The run directory is the artifact.** No hosted tracker is reachable, so config, metrics,
  environment and checkpoints all live together under `/kaggle/working/runs/<run-id>`.
