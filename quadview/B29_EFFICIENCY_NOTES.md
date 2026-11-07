# TriView B29 — efficiency and recentered XYZ head translation

Date: 2026-11-07. Parent: tested B28-103, `3ebe512c830a8e7467717d85d1cd0b7f52c5e4ba`.
Branch: `experiment/triview-b29-recovery-depth-perf-20261107`.

## Scope and user observations

The user reports B28 solved the crashes. This build preserves its source ownership,
located-pose, process-lifetime gamma tables, world gate, resize and checked restart
architecture. Seam experiments are postponed until the user supplies headset
screenshots. No appearance matching, guard crop or feather change is included.

Latest user steering prioritizes performance and efficiency. Peripheral depth
flicker was absent/rarer above 30 real FPS, and occurred around 25 FPS or below
with VectorXR reprojection. This is evidence of a timing/throughput correlation,
not proof of a fixed FPS threshold or a depth-age-limit defect.

User also reports XYZ head scaling X=3, Y=Z=1 creates diagonal movement while
uniform XYZ scaling behaves correctly.

## Implemented changes

1. **Head scaling axes:** the old formula was `R * (gain * tracking_delta)`.
   It amplified the runtime room axes before recentering them into player axes.
   Unequal gains and a nonzero recenter yaw mix lateral and forward movement.
   The new formula is `gain * (R * tracking_delta)`, before the game's view
   rotation. It uses the existing standing origin and recenter rotation, not
   live HMD orientation. Looking around cannot rotate the gain axes. Existing
   settings/keys, gain limits, world scale, eye offsets and roomscale pawn
   movement are preserved. The fix applies to the common camera path across
   the modes where this opt-in head scaling already applies, not only ID7.
2. **Shader ALU:** port only `QuadViewComposite.hlsl` from B27 commit
   `b024570edbbdc8852aa7e7e2e508235c228ca245`: skip the context homography under
   fully opaque foveal pixels, and share crop/output normalization across the
   six existing sharpening taps. No B27 C++/lifecycle changes are ported.
   Four depth samples, source sampling, sharpening controls, clamp behavior,
   feather and output transfer function remain. Reassociation can cause tiny
   floating-point rounding differences; Windows WARP checks must pass.
3. **Depth housekeeping:** active capture no longer repeats its pool pruning
   from Present, because the capture path already prunes. Disabled capture
   continues safe retirement attempts. Obsolete-size slots may be retained
   until the next matching capture or disabled-mode pruning; the pool remains
   bounded at 12. NGX export discovery retries at most once per second after
   queue/fence tracking is installed, rather than scanning DLL exports every
   Present. Missing/late exports retry; capture/submission work is never gated
   by this timer. Reset-hook lookup is deferred until the DLSS output size
   matches the periphery, avoiding unnecessary lookup locks on foveal passes.

This is a conservative efficiency patch. No numerical FPS improvement is claimed
without matched in-game measurements. It adds no GPU pass, source render, DLSS
operation or output-resolution change. Restart recovery is not rewritten.

## Depth investigation and remaining questions

B21's recent submitted-depth policy remains approximate with the same 250 ms
limit. At 25 FPS a normal frame is about 40 ms, so that limit alone does not
explain the observation. Do not increase it or hold arbitrary old depth as a fix.

Possible backlog-sensitive mechanisms include all 12 slots being GPU-busy/leased,
and foreign-queue snapshots waiting for CPU-visible fence completion. Neither
is established from the user's observation alone. Foreign queue wrappers must
not be assumed to be the same ordered GPU queue. All original completion and
lease requirements are preserved.

A separate review identified that B28 world invalidation does not explicitly
invalidate the depth selector's same-sized recent snapshots. That potential
old-world-depth window remains separate work; this patch does not claim exact
color/depth provenance or a complete flicker fix.

The restart state machine can remain pending if closed-draw/engine-tail/consumer
proof is unavailable. No timeout bypass or speculative retirement change is
introduced. Investigate precise stalled conditions if the user reproduces it.

## Validation and acceptance

- Guarded overlay applied to the fully generated B28 backend; final B28 and B29
  integration checks verify frozen pose, gamma lifetime and retirement wiring.
- Portable C++ suite includes the production head-scaling helper; its yaw sweep
  covers 2,190 combinations of recenter angle, gains and movement, and reproduces
  the old diagonal error. Additional actual pinned GLM integration checks cover
  quaternion/vec3 compilation and lateral, unit and uniform gain behavior.
- Shader source allowlist requires the exact pinned B23 or B27 shader, while
  independently preserving B23's entire depth-warp function and output encoding.
- New helper also runs under ASan/UBSan in CI. Local sanitizers disable LSan,
  which is unavailable under this host's tracing environment.
- Windows CI remains responsible for the restricted exact SDK, full backend
  compilation, FXC /WX and WARP pixel/geometry checks. Local source generation
  skips Windows-only shader embedding and does not claim a Windows build.

## Short headset checklist

1. Recenter facing forward. Enable XYZ with X=3, Y=1, Z=1. Move sideways,
   forward/back and vertically; sideways motion must not add forward motion.
2. Turn/recenter in another direction and repeat. Test all gains=1, all=3,
   and the hold-bypass key. A live head turn should not change the gain axes.
3. Compare B28/B29 at identical crop, periphery resolution, NR, sharpening,
   VectorXR settings and scene. Record real GPU frametime/FPS; no guessed gain.
4. If low-FPS flicker returns, record FPS plus the backend log. Useful depth
   counters: copied/submitted/used/missing, age_us, slots and foreign_queue.
   The last `reason` can describe a rejected foveal evaluation, not the true
   cause of a peripheral miss; it is not conclusive by itself.
5. Repeat a short B28 resize/reload/runtime smoke test. Retain B28-103.
