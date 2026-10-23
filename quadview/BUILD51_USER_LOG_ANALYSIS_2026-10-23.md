# Build51 user log analysis — 2026-10-23

Analyzed `upload/log(20261023-084331).txt` (14,447 lines; 7,374,396 bytes) from 11:35:50.262 to 11:43:07.875 (log timestamps; timezone unspecified), a 437.613-second capture. The user separately confirmed Build51 worked in the headset. This log shows successful Quad Views output periods, followed by a real freeze during a later Quad Views → DuoView request. Build52’s foreground MPC change is not covered by this log and has not yet been headset-tested.

## Quad Views activity

| Window | Active method / generation | Interval | Last emitted HookTrace counters | Sampled submit records |
|---|---|---|---|---|
| First | ID7 / gen3 | 11:37:05.786–11:39:05.505 (119.719 s) | copy 3,850 at 11:39:04.853; XR submit 3,856 at 11:39:05.020 | 60; all `held=false`, `eyes=2` |
| Second | ID7 / gen5 | 11:39:14.806–transition begins 11:42:41.575 (206.769 s) | copy 6,127 at 11:42:41.181; XR submit 6,137 at 11:42:41.480 | 103; all `held=false`, `eyes=2` |

The log parser found 163 fresh stereo submit records and 163 copy-enqueued records, with zero held submits. These are sampled log records, not frame totals; 72 submit samples have no same-serial copy sample because the two log sites are throttled independently. HookTrace counters increment on every event but emit only early records and periodic samples; their last values imply about 9,977 copy enqueues and 9,993 submit calls across the two ID7 generations, or roughly 30–32 calls per second while active. A few calls may follow the final one-second sample. These are event-rate proxies, not confirmed headset frame rate or GPU completion. The largest sampled gap inside an active window was 2.462 seconds; the 27.194-second trailing gap belongs to the failed transition.

There were three transient `[QuadView][OutputWaiting] no executed source` warnings: 11:37:05.844 at first entry, 11:39:14.839 at re-entry, and 11:40:33.372 during target replacement. Two `No stage views to submit` warnings coincide with the first two entries. Submits resume after each; these do not explain the later sustained freeze. No explicit gaze-loss or gaze-reset sequence appears, though the log is too sparse to establish continuous gaze quality.

## Transition failure

No ID6 commit appears. The last successful owner-bound RHI callback completes at 11:42:41.511. At 11:42:41.575, the render thread receives a two-view family (`count=2 capacity=2`); at 11:42:41.598, its Slate callback is rejected as `quad_without_owner`, with status “Waiting for tracked render-thread/RHI owners to execute at mode commit.” The same rejection path persists: eight HookTrace samples were emitted, and its per-generation counter reached 14 by 11:43:07.869. Six two-view render-family rejections occur after the transition starts. There is no subsequent RHI-entry/worker-return trace, while render-thread callbacks continue through 11:43:07.875. The last GT engine-registration sample is 11:42:40.693 and reports three pending engine tickets. At 11:43:07.867 the log reports an engine-tick age of 16,074 ms. This is a real mode-switch stall, not just a temporary missing submit.

The log is consistent with a missing ownerless RHI-tail servicing path as a contributor: the transition waits for tracked owners, but the two-view callbacks are rejected before they can reach the hooked RHI worker path. It does not prove which ticket is permanently stuck or that a maintenance callback alone will retire it; retirement still requires the authenticated owner tail to execute.

## Targets, errors, and timing

Twelve target-lifetime records describe three sets of four independent, property-owned textures; all show `capture_every=false` and `capture_movement=false`. The published sets are 5136×2040 at 11:37:06.745 (gen4), 5136×2040 at 11:39:15.580 (gen7), then 7368×2928 at 11:40:34.158 (gen8). The last size contains about 2.06× as many pixels per source as the earlier sets. No explicit quality, scale, or `gpu_timing` setting change is logged, so the cause of the resize is unknown; there is no evidence of per-frame target allocation.

Startup noise includes 58 DirectX 12 framework-init retries, three back-buffer/setup failures, three `XR_ERROR_TIME_INVALID` end-frame failures, and three `XR_FRAME_DISCARDED` begin-frame failures between 11:36:08 and 11:36:11. The later action-sync errors total three `XR_SESSION_NOT_FOCUSED` records: one at 11:41:02 and two at the frozen tail. The parser’s 13 “runtime-fault signature” hits are startup binary-scan diagnostics (“attempted dereference” / instruction-pattern mismatch), not exception or crash records; no explicit access violation, unhandled exception, or crash dump appears.

Logging itself is substantial: 10,498 HookTrace lines account for 6,799,084 bytes (about 92% of the file), averaging 24 lines/s and 15.5 kB/s across the capture. This measures output volume, not its CPU cost. There is no usable GPU timing result in the log. The existing QuadView timestamp brackets only the compositor’s fullscreen `DrawInstanced`; it excludes Unreal’s four source renders and CPU-side view-family/gather work.

## Safest performance investigations

1. For a baseline, reduce HookTrace sampling while keeping brief transition snapshots. It produced about 6.8 MB here; any runtime benefit from less logging remains unmeasured.
2. Record compositor GPU time alongside separate Unreal source-render and CPU/RHI/gather timings. The current compositor timer is not a total-frame measurement.
3. Check why source dimensions changed from 5136×2040 to 7368×2928. If that size is not required, compare a controlled run at the earlier size; this is a measured workload difference, not proof of a frame-time increase.
4. After timing each stage, test source-resolution or peripheral-view quality changes and compare the same scene and runtime. This log alone cannot support a speedup estimate.

## Foreground MPC change planned for Build52

The current MPC runtime sets `IsFOVEnabled=0` and `DepthScale=1` for the shared `MPC_FOV`. It caches the collection/library and reflection handles with UObject identity checks, reads values each tick, writes only scalars that drift, and restores the saved original values when the feature is disabled or Quad Views exits. The compiled harness exercises this runtime include; headset behavior for Build52 remains unverified.
