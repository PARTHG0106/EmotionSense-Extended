# 04 - Model benchmark plan

Every task gets a primary model and at least two baselines, compared under one fixed
protocol with subject-and-camera-disjoint splits.

| Task | Primary | Baselines | Selection metric |
| --- | --- | --- | --- |
| Detection | YOLO11-m, person class, fine-tuned on CrowdHuman + low-res augmentation | RT-DETR-L, Faster R-CNN R50 | mAP@50-95 on site footage, >= 25 FPS/stream |
| Tracking | BoT-SORT with ReID | ByteTrack, StrongSORT | HOTA, IDF1, **ID switches per hour** |
| ReID | OSNet-AIN, FastReID BoT-R50 | TransReID | Rank-1 + mAP on Occluded-Duke and a downscaled MSMT17 protocol; separately on LTCC/PRCC |
| Pose | RTMPose-m | YOLO11-pose, MediaPipe (CPU reference) | AP on CrowdPose occluded subset |
| ADL | VideoMAE-v2-S fine-tuned | SlowFast-R50, X3D-M, TimeSformer | per-class F1 on Toyota Smarthome |
| Fall | pose kinematic rules + ST-GCN++ | 3D CNN video classifier, rules only | recall >= 0.95 at <= 1 false alarm per resident-week |
| Temporal behaviour | TCN | LSTM, GRU, Transformer | next-window prediction error |
| Anomaly | z-score vs personal baseline + Isolation Forest + LSTM-AE ensemble | each method alone | AUC and caregiver-rated precision@10 |
| Reasoning | strongest available LLM | template renderer (always kept as fallback) | field completeness, grounding audit |

## Required ablations

| Module | Ablations |
| --- | --- |
| Detection | with/without low-res augmentation; input resolution sweep |
| ReID | body -> +face -> +gait -> +priors; standard vs clothing-change protocol |
| Pose | model size vs FPS vs occluded AP |
| ADL | RGB only vs skeleton only vs fusion; window 2s/4s/8s |
| Fall | rules only vs model only vs rules+model, reporting false alarms per hour |
| Anomaly | z-score only vs +IForest vs +LSTM-AE ensemble |
| Identity | per-signal ablation and per-signal weight sensitivity |

## Why fall detection is rule-first

Kinematic signature: vertical drop of the hip/shoulder centroid greater than 0.4x body
height within 1.0 s, followed by sustained near-horizontal torso orientation, followed by
post-event stillness beyond 10 s with no self-recovery transition. The learned model
adjusts confidence; the rule bounds behaviour on footage no model has ever seen and is
directly explainable to a caregiver.

Vision-only fall models trained on Le2i / UR-Fall overfit staged falls and degrade sharply
on real homes. This is the most over-claimed result in the fall-detection literature, and
the benchmark protocol here is designed to expose it: continuous footage, false alarms per
resident-week, no balanced-clip F1 as a headline number.
