# VectorXR #22b — live A/B/C research file (review-only)

Based on green #42 (fda80c0) plus the #45 internal-depth / pass-through fixes.
Do not install or merge without Claude's generated C++ review. Never treat test output as headset evidence.

## Usage

Copy `test-presets22/live-AB.txt` to `%LOCALAPPDATA%\VectorXR\framegen-research.txt` before launching the game. This is the existing A baseline (Dynamic cap 4), with UEVR world tracing explicitly enabled. The VectorXR research trace must also be enabled before start.

While the game is running with VectorXR's presenter thread active, save the same research file after changing just one of:
- `VECTORXR_CONTENT_CLOCK21=1`: B (release-phase content clock). Set back to 0 for A.
- `VECTORXR_MAX6_HYSTERESIS21=1`: C (Max6 hysteresis). **Meaningful C testing requires `VECTORXR_FRAMEGEN_FLOW_DYNAMIC_MAX=6` set BEFORE launching the session.** This max is NOT a live-safe switch. To compare A vs C within one session, start with max=6 and toggle only the hysteresis line.
- `VECTORXR_FRAMEGEN_RUNTIME_DEPTH=0`: stop sending depth to the OpenXR runtime, without stopping depth capture/synthesis internally. Set back to 1 to restore.

File metadata is checked at most every second on the compositor thread and only outside the presenter's mutex. An edit appears at the next check. Invalid, large (>64 KiB), or unreadable files are ignored. Environmental variables take precedence over file values.

Changing **any other key** mid-session is logged as `takes effect next session`; it is not applied. Do not edit multiple unrelated keys expecting a live layout or capture change. The content clock's phase-mean estimator is deliberately reset when B toggles. Camera pose and exact-frame selection remain on the original clock.

## Trace

VectorXR's generated CSV starts with the normal header, then `0,21,2,0,0,0,0,0,0` (schema v2 marker). On each applied switch, `kind=8`, `frame=1` (content clock), `frame=2` (hysteresis), or `frame=3` (runtime depth), and `aux=0/1`. A per-session CSV filename may still contain the original A/B/C mode because it is created once; split analysis by kind-8 markers, not filenames. Older readers should ignore unknown kinds 0 and 8. The UEVR `ResearchTrace21.hpp` source is intentionally unchanged at schema 1.

CI includes deterministic file-mtime tests and a fake-runtime live transition test, with a sanity bound on pacing continuity and output order. No GPU/headset equivalence claimed.

## Source and evidence

The workflow emits `vectorxr22-generated-cpp.patch` (full #22 changes from #36) and `vectorxr22b-generated-cpp.patch` (incremental changes after #45). Green #42's verified generated diff is the baseline. Both patches, compile/test logs, and this readme belong in the review artifact. All switches preserve #42 mode when unset (except the requested default-on safety switch for Cheeky, an unrelated project).
