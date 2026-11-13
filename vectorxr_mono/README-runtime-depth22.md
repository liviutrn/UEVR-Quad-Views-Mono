# VectorXR #22 — runtime depth A/B (13 November 2026)

Base: VectorXR research #21 / repository commit `7f15a464ac0fa17a5d766c96cfc0ad4727943336` and pinned upstream DienerTech/vectorxr `8fffa72` (v0.20.1).

**Review-only build. Do not install until Claude has reviewed the generated-source patch.**

## Runtime depth switch

Add `VECTORXR_FRAMEGEN_RUNTIME_DEPTH=0` to `%LOCALAPPDATA%\VectorXR\framegen-research.txt` or set it as an environment variable, then restart the game. `1` or unset is the #36 default, preserving runtime depth.

At 0, all projection views submitted through the FrameGenPresenter to OpenXR have their `XrCompositionLayerDepthInfoKHR` chains removed. This includes inline, startup pass-through, JIT as-is/exact, generated, repeated, and legacy presenter paths. The source frames and depth chain consumed by VectorXR for optical-flow synthesis are **not modified**. A depth node appearing behind an opaque unknown view-chain node causes that view's remaining output chain to be dropped only in the explicit off mode (safe exclusion).

Note: this is an A/B for **runtime submission**, not disabling internal depth capture or changing SteamVR settings. Output submitted when VectorXR Frame Generation is not running through the presenter is outside this switch.

The #21 startup mode line now includes `runtimeDepth=0` or `runtimeDepth=1` and is logged once per session.

## #21 trace corrections

Kind-7 rows retain the same schema and auxiliary flags. For paths 6/8 with a previously shown frame, `pose_xr` carries the fraction of that prior frame (not a newly synthesized fraction, bit 13 remains clear). Exact extrapolation is logged as fraction 0, not 1,000,000. All other kind-7 fields are unchanged.

## #18 fixture and tests

For each off-timeline miss, the warm-up test prints the image class (real copy vs generated/fallback), lead snapshot, allowed cap, ring ceiling snapshot, and GPU capture/analysis snapshot. The last four values are **test-window snapshots**, not data captured at the individual refresh; no pacing or threshold changes.

The fake OpenXR runtime records depth chains on **every projection layer and eye**. `TestRuntimeDepth22Off` checks the JIT and legacy renderers, real copies and generated outputs, and also confirms internal GPU depth capture continues. Existing tests and the kind-7 trace test run unchanged.

CI evidence artifact contains `vectorxr22-generated-cpp.patch`, a no-index generated C++ diff against #36's generated tree (before #22), plus logs.

## Test preset

`test-presets22/RD0.txt` is the #21 A-baseline preset plus `VECTORXR_FRAMEGEN_RUNTIME_DEPTH=0`. Test this only after Claude's review and the #21 timing/capture sitting; compare at SteamVR 120 Hz using the same scene and unchanged FG/NR settings.
