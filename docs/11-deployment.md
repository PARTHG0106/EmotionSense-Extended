# 11 - Deployment

## Topology - edge first

```
Per site:
  [ Edge box: RTX A2000/4060-class or Jetson Orin ]
     L1 perception per camera stream (ONNX / TensorRT, FP16 or INT8)
     local Redis (transient frames), local Postgres (events)
     outbound: encrypted event sync only. No video egress.
  [ Central server (optional, multi-site) ]
     L3 behaviour batch jobs, L4 reasoning, API, dashboard, backups
```

Edge-first is the correct default: video stays inside the building, the system survives
internet outages, and the privacy story is defensible. Cloud-only is acceptable only where
video egress is contractually permitted and bandwidth is guaranteed.

## Packaging

Docker Compose for a single site: `edge-perception`, `activity-worker`, `behavior-worker`,
`api`, `postgres`, `redis`, `dashboard`. Kubernetes only for multi-site central services.

Model registry: versioned weights with SHA, exported to ONNX then TensorRT per target
device. Every event row records the model versions that produced it.

## Degradation ladder

`full -> reduced_fps -> no_reid -> pose_safety_only -> ops_alert`

Fall detection deliberately survives to the last rung. Behavioural claims stop as soon as
identity is unreliable.

## Observability

Prometheus/Grafana on per-camera FPS, queue depth, alert rate by severity, `unknown`
identity rate, and model latency. A rising unknown-identity rate is the earliest warning of
camera drift or a stale gallery.

Backups: nightly encrypted Postgres dump; quarterly restore drill. Retention runs as
partition drops.

Runbook covers the four real failure classes: camera down, GPU/model failure, false-alarm
storm, identity collapse.
