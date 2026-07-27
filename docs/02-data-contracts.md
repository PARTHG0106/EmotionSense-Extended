# 02 - Data contracts

The contracts in `src/wellbeing/contracts/` are the single source of truth for every
interface in the system. They are pydantic models, validated at each layer boundary, and
they are what makes explainability mechanical rather than generative.

## Contract inventory

| Contract | Produced by | Consumed by |
| --- | --- | --- |
| `PerceptionFrame` / `TrackObservation` | L1 | L2 |
| `IdentityAssignment` | L1 identity resolver | L2, L3, UI |
| `ActivityEvent` | L2 | L3, L4, storage, UI |
| `DailyFeatures` | L3 | L3 baselines, L4 |
| `Baseline` | L3 | L3 anomaly, L4 |
| `AnomalySignal` | L3 | L4 |
| `Alert` + `Explanation` | L4 | UI, notifications |

## Invariants enforced in code

1. Every event has `ts_start <= ts_end` and a non-empty `evidence` list.
2. Every confidence is in `[0, 1]`.
3. `IdentityAssignment.kind == "unknown"` requires `subject_id` to be an ephemeral id and
   forbids downstream baseline updates.
4. `Alert.explanation` must contain all six required fields, or the alert is emitted as a
   structured card with no prose.
5. `DailyFeatures.completeness` records the fraction of the bucket covered by working
   cameras. Anything below the configured minimum is excluded from baselines instead of
   being treated as zero activity - this is the single most common source of false
   "resident was inactive all day" anomalies.
6. `model_versions` is attached to every event so any alert can be reproduced later
   against the exact models that produced it.

## The six required explanation fields

| Field | Filled from |
| --- | --- |
| `what` | `ActivityEvent.label` + duration |
| `when` | `ts_start` / `ts_end` in resident-local time |
| `why_flagged` | `AnomalySignal.metric`, `deviation_sigma`, fired rule ids |
| `baseline_delta` | `observed` vs `baseline_median`, in human units |
| `confidence` | fused identity + model confidence, naming the weakest link |
| `check_next` | rule-mapped caregiver action from a curated playbook |

Text generation happens only after all six fields exist. The LLM renders; it does not
decide.
