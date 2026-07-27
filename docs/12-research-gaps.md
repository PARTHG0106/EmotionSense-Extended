# 12 - Research gaps and future scope

## Where this design is genuinely weak

1. **No public dataset contains real elderly home footage at the needed scale.** Toyota
   Smarthome is the only strong option and it is small and gated. Expect a large
   benchmark-to-site drop and budget 20-40 hours of site-specific annotation. Any plan that
   skips this is fiction.
2. **Clothing-change ReID is unsolved at CCTV resolution.** Even trained on LTCC/PRCC,
   Rank-1 of 60-70% is realistic. The mitigation is architectural, not modelling: permit
   `unknown`, lean on spatiotemporal priors, and design the UI to tolerate identity gaps.
3. **Fall recall on real, occluded, night-time falls is unproven.** Public numbers come
   from staged falls in clear view. A wearable or radar/bed sensor should corroborate the
   critical path; vision alone should not be the sole life-safety safeguard.
4. **The well-being score has no clinical validation.** It is a heuristic composite and
   must be labelled an operational indicator until correlated against a validated scale
   (for example a Barthel/ADL index) with clinician involvement.
5. **Anomaly ground truth barely exists.** Precision can only be estimated from caregiver
   feedback, which is sparse and biased toward what staff already noticed. Accept a wide
   initial uncertainty band.
6. **Multi-camera cross-view identity is out of scope for v1.** One camera per zone with
   handoff via zone topology is the pragmatic start.
7. **Concept drift from health decline is fundamentally ambiguous.** The system cannot
   distinguish "declining, update the baseline" from "declining, this is the alert" without
   clinical input. Current answer: flag as a trend, escalate to a human, never silently
   absorb it.

## Future scope, priority ordered

1. **Sensor fusion** (bed pressure, door contacts, PIR, mmWave radar for bathroom and
   night). Highest value per unit effort: non-visual sensors fix precisely the cases vision
   fails.
2. **Wearable corroboration** for falls, turning a probabilistic vision alert into a
   high-confidence one.
3. **Clinician feedback loop** with structured outcome labels, enabling supervised
   calibration of risk scoring.
4. **Multi-camera cross-view tracking** with a scene graph and topology priors.
5. **Resident state model / digital twin** to forecast next-day risk rather than only
   detect deviation.
6. **Federated learning** across sites so personalization improves without video leaving a
   building.
7. **Continual learning under safety constraints**: gallery and threshold updates gated by
   drift tests with a rollback path; no unsupervised updates on a life-safety path.
8. **Edge INT8 quantization** to reach 6-8 streams on one mid-range GPU.
