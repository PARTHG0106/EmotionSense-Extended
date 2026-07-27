# 03 - Dataset plan

## Selection rule

A dataset earns a place only if it improves one of: low-resolution robustness, occlusion
robustness, elderly movement patterns, real falls, indoor home context, temporal
understanding, or identity persistence. Everything else costs GPU hours and inflates
numbers that will not survive deployment.

## Detection

| Dataset | Why here |
| --- | --- |
| CrowdHuman | Heavy occlusion; partially hidden bodies behind furniture are the normal indoor case |
| WiderPerson | Small-scale persons, matching wide-angle CCTV where a person is 60-120 px tall |
| COCO (person) | Pretraining only. Do not fine-tune: its viewpoint distribution is nothing like fixed indoor CCTV |
| Open Images / Objects365 | Furniture and object classes (bed, chair, cup, walker) for interaction cues |

## Tracking

MOT17 / MOT20 for the standard HOTA/IDF1 protocol; **DanceTrack** because non-linear motion
with similar appearance is the closest public proxy for two similarly dressed residents in
one room; TAO for long-horizon re-entry.

## Person ReID (highest-priority block)

| Dataset | Why here |
| --- | --- |
| Occluded-Duke | Direct proxy for furniture and doorway occlusion |
| MSMT17 | Multi-camera, multi-season, lighting variation |
| Market-1501 / DukeMTMC / CUHK03 | Baseline comparability with published work |
| PRW | Detection-plus-ReID without clean crops, matching the real pipeline |
| **LTCC, PRCC, DeepChange, VC-Clothes** | **Clothing change.** Residents change clothes daily; standard ReID benchmarks assume they do not, which is exactly why lab ReID numbers collapse in homes. Non-optional here. |

## Pose

COCO Keypoints as base, **CrowdPose weighted highest** (occlusion), MPII, Halpe
(whole-body), Human3.6M for 3D supervision of lying and crouching geometry.

## Action / ADL

| Dataset | Why here |
| --- | --- |
| **Toyota Smarthome (+ Untrimmed)** | The most relevant public dataset in existence for this product: real elderly subjects, real apartments, fixed cameras, untrimmed streams |
| NTU RGB+D 60/120 | Cheap skeleton-based transfer for posture and transition classes |
| Charades | Untrimmed indoor multi-label activity; concurrent activities |
| EPIC-Kitchens | Fine-grained meal preparation and hand-object interaction |
| Kinetics-700 / SSv2 | Pretraining only |
| **ETRI-Activity3D** | Explicit elderly-vs-young activity comparison; age-specific motion priors |

## Fall detection

| Dataset | Why / caveat |
| --- | --- |
| UP-Fall | Largest multimodal controlled set (vision + IMU) |
| Le2i / UR Fall / Multicam Fall | Vision falls in rooms, but **all staged by young actors**: sanity checks, not validation |
| SisFall / FallAllD / MobiAct | Wearable IMU; only if a wearable is in scope |
| **HQFSD / CAUCAFall** | Harder, more realistic occluded and multi-person fall footage |

## Gait

CASIA-B (clothing and bag covariates), OU-ISIR (scale), and **GREW + Gait3D**, which are
the only in-the-wild sets that transfer to CCTV conditions.

## Anomaly

Avenue, UCSD Ped2, ShanghaiTech for method baselines only. UCF-Crime and XD-Violence are
**out of scope**: violence detection is not the anomaly class this product cares about.
Real anomaly supervision comes from the resident's own baseline.

## Smart-home / sensor behaviour

CASAS, ARAS, Opportunity, PAMAP2, UCI HAR. Use these to develop and validate the routine
and anomaly algorithms **before** any video exists. CASAS in particular provides months of
real single-resident elderly routine data that no video dataset offers.

## Audio (optional)

AudioSet + ESC-50 for impact sounds and calls for help; CREMA-D / MSP-Podcast only if
vocal distress is genuinely required. Recommendation: ship voice-activity and impact-sound
detection only. Speech emotion recognition adds real privacy exposure and little clinical
value.

## Synthetic supplement

Render the edge cases public data lacks: night-time falls, falls behind furniture,
walker/wheelchair use, two residents in identical clothing. Cap at ~20% of any training mix
to avoid domain collapse.

## Lab-to-home domain mismatch

This is the failure that kills projects like this. Countermeasures in value order:

1. **Degradation augmentation as a first-class pipeline**: downscale to 96-192 px person
   height, JPEG artifacts, motion blur, sensor noise, low-light gamma, IR/greyscale.
   Train degraded, validate degraded.
2. Viewpoint warping to simulate ceiling and corner mounting.
3. A held-out **real site footage** validation set, even if only two hours. Nothing ships
   without a number on it.
4. A per-site calibration pass: zone annotation, homography, resident enrollment.
5. Always report both numbers. A public-to-site gap above ~25% relative means not
   deployable.
