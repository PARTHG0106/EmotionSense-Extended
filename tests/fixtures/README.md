# Test fixtures

## `trace_day.jsonl`

A JSON Lines perception trace: one `PerceptionFrame` per line, replayable with

```bash
python -m wellbeing.pipeline.replay tests/fixtures/trace_day.jsonl
```

It encodes a single unambiguous fall for `resident:ana` in the living room:

| Frames | Time | What it represents |
| --- | --- | --- |
| 1-2 | 14:00:00.0-14:00:00.5 | Standing upright, walking at 25 px/s |
| 3 | 14:00:01.0 | Centroid drops 100px against a 220px body (0.45 > the 0.40 threshold) within the 1.0s drop window |
| 4-16 | 14:00:02.0-14:00:14.0 | Horizontal torso held, speed at 1 px/s, well past the 3.0s horizontal hold and 10.0s stillness requirements |

Every threshold this trace crosses is defined in `configs/default.yaml` under
`activity.fall`. If you change those values, this fixture's expected outcome changes with
them, which is the point: the fixture is a regression test on the tuning, not just the code.

**No pixels are stored.** The trace carries geometry, posture and identity references only,
which is also why real traces can be retained for the 30-day keypoint window while raw video
is never persisted at all.
