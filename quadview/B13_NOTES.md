# TriView B13 independent review — 2026-11-06

B12 parent: d7ee036523ddd333a02c6afc5ab72af662a89752; Actions run 42131429171.
Experimental branch only; preserves DuoView and B12.
CI and WARP tests are NOT a headset test.

## Confirmed fixes
- Producer depth copies now have a separate D3D12 fence for each pool slot. The
  B12 global fence was signalled from potentially different DIRECT queues with
  increasing values. If the later queue completed before the earlier one, its
  higher value could falsely retire the earlier copy (GPU resource hazard).
  Slot leases and slot reuse now inspect the corresponding recording's fence.
  Main compositor-queue read ordering remains dependent on queue identity.
- Shader depth marching no longer interpolates from a previous UV outside the
  periphery bounds when the first valid ray meets a surface.
- Autostart logs successful ID7 commit only if active method is actually ID7.
- READ_FIRST now describes current depth ON default, diagnostic behavior,
  startup, resize and headset-test procedure instead of obsolete B9 claims.

## Remaining open / falsification criteria
- NGX depth copy assumes input NON_PIXEL_SHADER_RESOURCE at Evaluate. Validate
  on RTX hardware; not a proven BSOD cause.
- No WARP regression verifies the B12 24-step marched warp on near occluders
  with ground-truth stereo; B12 offline mean-error 10.06 -> 8.47 is one case.
- 250ms depth age window does not enforce exact producer-frame identity.
- OpenXR depth swapchain skipped at startup when ID7 selected; switching to
  Native Stereo can leave OpenXR depth unavailable until swapchain recreation.
  This B12 memory optimization remains enabled for a comparable B13 test.
- Resizing uses make-before-break; engine lifecycle and GPU retirement on
  actual world/level transitions remain headset-only validations.
- 24-depth-sample marching shader adds GPU work; CI proves no VRAM/FPS gain.
- BSOD root is unknown; obtain Windows stop code, LiveKernelEvent, minidump.
- B13 requires one cautious headset test; compare B12 at identical settings.

## What CI checks
- Windows full backend/frontend, 25 QuadView tests, 4 pinned DuoView tests,
  6 independent DuoView tests, 41 original compatibility tests, plus 9
  portable sanitizer targets and source-level B13 generated-code assertions.
- The generated-source test asserts per-slot producer fences, no shared
  multi-queue signal, out-of-bounds shader guard and accurate startup logging.
- Actual multi-queue GPU interleavings, shader stereo parity and runtime VRAM
  allocation are NOT simulated by these tests.
