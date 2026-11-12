# DuoView Mono B40 seam — full architecture port
Date: 2026-11-12. Distinguish source, CI, and headset verification.

Source baseline: experiment/triview-duoview-parity-phase2-20261112 at ecbb12c3292285a89c17c2cc5a33077ed005ca3a; Phase1 CI #158 passed. This work stays on experiment/duoview-b40-mono-seam-20261112.

## Architecture preserved
- Replace Phase2 prototype four-probe per-output-pixel matcher. This is a real B40 spatial sampling + persistent GPU history + temporal smoothing port.
- 32 border knots on a single Mono fovea, 4 deterministic subanchors/knot = 128 spatial centers.
- B40 exact displayed pixel-center edge projection and sharpened/anti-vignette corrected sample reference; extra-wide B43 ring display-only.
- B39 interior 3x5 paired RGB differences per center = exactly 1,920 paired focus/context samples per mono frame, identical to TriView per eye. Mono does not duplicate work for right eye.
- Group-of-four componentwise trimmed mean; 3-point componentwise median; 2-point mean; fewer than two usable anchors holds prior correction.
- Single true queue-owned D3D12 history UAV, shared by all fence-retired OpenXR copy slots. Per-slot 64-float4 output stats; UAV-before/after dispatch barrier and UAV->SRV transition before display. Queue identity must remain stable. No CPU readback, no shader compilation in XR frame.
- Exact B40 bounded EMA: dt=min(elapsed,50ms), alpha=dt/(tau+dt), rate limit=(100/tau)*(dt*0.001). New histories start neutral and ramp. Invalid samples HOLD. There are NO gaze, scene, crop, settings, timeout, or validity resets. A new device/queue/session necessarily creates a fresh history buffer.
- 32-knot RGB residual interpolated around the real fovea boundary and applied ONLY to context with the original B40 smooth fade over outward reach; B38 preserved inward raw context feather. Focus texels are never stretched or blurred.
- Same B31 calibrated brightness-only anti-vignette applied to displayed focus and sampled statistics, optional B43 strength 0-20/max0.80 and 2x radius ring.
- Native two-source and gathered fallback both use this SAME shader mathematics, same shared temporal state, same source format.
- Default seam OFF until headset verification; B40 temporal presets Fast 75ms, Balanced 200ms, High 350ms (default), Maximum 600ms, 48px tangential radius, 32px interior reach, 240px exterior reach and 12px inward anchor.

## Mono optimizations
No stereo homography or depth reprojection is needed: fovea/periphery sample the same full-FOV UV in Mono. Right-eye duplicate compute dispatch removed. Everything else in B40 correction architecture is kept intact. The sampling rate, knot count and temporal rules are not reduced.

## Validation
- Pinned v208d subtree integrity, source-checkpoint/generative scripts, B43 TriView source integrity.
- Windows fxc offline compilation of both native/gather pixel AND compute shaders.
- 4-minute sanitizers and all existing TriView WARP/UEVR compatibility tests.
- New source contract and numerical test gates inspect real queue ownership, GPU barriers, trim/EMA and 32x4x15 samples.
- User headset tests required; matching algorithms do not guarantee identical output because Mono and stereo differ in projections, pixel histories, source shading and depth. Performance and perceptual flicker remain unverified.

At most three headset questions: 1) Does the seam disappear with still and slow gaze/head movement? 2) Is there flicker at low real FPS, scene reload or mode switch? 3) Is TriView ID7 unchanged?
