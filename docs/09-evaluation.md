# 09 - Evaluation strategy

## Per-layer metrics and acceptance gates

| Layer | Metrics | Gate |
| --- | --- | --- |
| Detection | mAP@50-95, small-object AP, FPS | mAP >= 0.55 on site footage, >= 20 FPS/stream |
| Tracking | HOTA, IDF1, MOTA, ID switches/hour | HOTA >= 60, < 2 switches/hour/resident |
| ReID | Rank-1, mAP, clothing-change Rank-1 | >= 0.85 standard, >= 0.65 clothing-change |
| Identity system | resident/visitor accuracy, unknown rate, false-merge rate | >= 95% split accuracy, **false-merge <= 0.1%** |
| Pose | AP, occluded-subset AP | occluded AP >= 65 |
| ADL | macro-F1, per-class recall, similar-pair confusion | macro-F1 >= 0.70 |
| Fall | recall, precision, **false alarms per resident-week**, latency | recall >= 0.95, <= 1 FA/resident-week, latency <= 10 s |
| Behaviour | anomaly AUC, precision@10 under caregiver review, baseline stability | AUC >= 0.80, P@10 >= 0.6 |
| Reasoning | field completeness, grounding audit, banned-phrase violations | 100% complete, 0 unsupported claims in a 200-alert audit, 0 violations |
| System | end-to-end latency, uptime, alert precision, caregiver usefulness | >= 99% uptime, alert precision >= 0.7, usefulness >= 4/5 |

## Non-negotiable practices

1. **Split by subject and camera, never randomly.** Random clip splits leak identity and
   inflate essentially every published number in this field.
2. **Report false alarms per resident-week.** F1 on a balanced fall dataset is meaningless
   when a fall is a 1-in-100,000-frame event.
3. **Evaluate on continuous footage**, not clips: run 72 unbroken hours and count every
   alert the system raised, including the ones it suppressed.
4. **Replay harness**: the full L1-L4 pipeline must be reproducible from a stored
   perception trace with one command, so behaviour-layer changes are measurable without
   touching a GPU.
5. **Caregiver-in-the-loop review** monthly: sample 30 alerts, collect true/false labels,
   recalibrate per-resident thresholds.
6. **Shadow mode** for every new model version: run in parallel with suppressed alerts and
   compare against the incumbent for two weeks before it may raise a real alert.
