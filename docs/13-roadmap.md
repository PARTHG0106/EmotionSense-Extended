# 13 - Roadmap

Build incrementally. For each module: design the interface, explain the approach,
implement, test, validate on sample data, optimize, document. Do not start the next module
until the current one meets its exit criterion.

| # | Module | Exit criterion |
| --- | --- | --- |
| 1 | Dataset preparation pipeline | all datasets packaged as versioned Kaggle datasets, checksum-verified, format-converted, subject/camera splits fixed |
| 2 | Detection + tracking | HOTA >= 60 on internal low-res clips, >= 20 FPS/stream on target hardware |
| 3 | ReID + identity persistence | < 2 ID switches/hour/resident, resident-vs-visitor >= 95%, false-merge <= 0.1% |
| 4 | Pose estimation | occluded-subset AP >= 65 |
| 5 | Activity recognition | macro-F1 >= 0.70 on the Toyota Smarthome protocol |
| 6 | Fall detection | recall >= 0.95 with <= 1 false alarm per resident-week on continuous footage |
| 7 | Temporal behaviour modelling | stable 14-day baselines; drift test passes on replayed data |
| 8 | Anomaly detection | precision@10 >= 0.6 in caregiver review |
| 9 | Explanation layer | 100% of alerts carry all six fields; zero unsupported claims in a 200-alert audit |
| 10 | Dashboard + alerts | caregiver identifies resident state in under 5 s in usability testing |
| 11 | Evaluation + benchmarking | end-to-end replay benchmark reproducible from one command |
| 12 | Deployment packaging | compose up on the edge box, ONNX/TensorRT export, degradation ladder verified |

## Sequencing notes

- Modules 1-3 are the critical path and deserve the largest share of effort. Identity is
  the foundation everything else stands on.
- Modules 7-9 can be developed in parallel against **synthetic or CASAS sensor event
  streams** before video is production-ready. This removes the behaviour layer from the GPU
  critical path entirely.
- Module 6 should not be declared done on staged-fall datasets. It needs continuous
  real-footage evaluation, and ideally a second sensing modality.
