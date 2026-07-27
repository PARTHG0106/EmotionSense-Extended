# 01 - Architecture

## Product position

The original scope (facial emotion recognition) is a weak foundation for elderly care:
facial affect from low-resolution CCTV is unreliable and clinically close to meaningless.
The system therefore targets **longitudinal behavioural monitoring against personal
baselines**. Emotion, if used at all, is one low-weight optional signal.

## Layers

```
Cameras / mic / optional IoT sensors
   |
 L1 PERCEPTION   detect -> track -> pose -> ReID -> identity resolve
   |  PerceptionFrame
 L2 ACTIVITY     posture, transitions, ADLs, room events, falls
   |  ActivityEvent
 L3 BEHAVIOR     daily features, personal baselines, trends, anomalies
   |  BehaviorProfile + AnomalySignal
 L4 REASONING    alert assembly, explanation rendering, reports
   |  Alert + Report
 Dashboard / notifications
```

Rules that make this architecture worth having:

1. A layer may only consume the typed contract of the layer directly below it.
2. Only L1 touches pixels. L2 sees keypoints and boxes. L3 sees events. L4 sees rows.
3. The LLM never detects, never tracks, never sees an image, and never introduces a fact
   that is not present in the structured input it was given.
4. Every emitted object is timestamped, confidence-scored, and carries evidence ids.

## Multi-agent mapping

| Agent | Layer | Inputs | Outputs |
| --- | --- | --- | --- |
| Perception | L1 | frames | `PerceptionFrame` (tracks, boxes, keypoints, posture, identity) |
| Activity understanding | L2 | `PerceptionFrame` windows | `ActivityEvent` stream, fall decisions |
| Behavior understanding | L3 | `ActivityEvent` history | `DailyFeatures`, `Baseline`, `AnomalySignal`, trends |
| Reasoning and reporting | L4 | L3 + L2 rows | `Alert` with `Explanation`, daily/weekly reports, grounded Q&A |

## Failure modes and mitigations

| Layer | Primary failure | Mitigation |
| --- | --- | --- |
| L1 | ID switch after occlusion; ID switch between similarly dressed residents | multi-signal identity fusion, hysteresis, explicit `unknown` state, quality-gated gallery updates |
| L2 | voluntary lying-down misread as a fall | kinematic drop signature + horizontal hold + post-event stillness + self-recovery check |
| L3 | cold start; camera outage read as inactivity; health decline absorbed into baseline | 14-day warmup, `completeness` gating, sustained deviation reclassified as trend and escalated |
| L4 | fluent but unsupported claims | evidence-constrained rendering, required-field validation, banned-phrase check, fallback to structured card |

## Latency and backpressure

Perception budget is 150 ms per frame per stream. Fall alert end-to-end budget is 10 s.
Behaviour and anomaly work is batch (15-minute and nightly). Under load the system
**drops frames to the latest** rather than queueing: a monitoring system running 40 seconds
behind reality is worse than one running at 8 FPS.

## Graceful degradation ladder

`full -> reduced_fps -> no_reid (identity becomes unknown) -> pose_safety_only -> ops_alert`

Fall detection deliberately survives to the last rung, because it is the only life-safety
function in the system. Behavioural claims are suppressed as soon as identity confidence
drops below the configured floor.
