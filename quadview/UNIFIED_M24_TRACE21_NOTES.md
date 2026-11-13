# Unified UEVR TriView B43 + DuoView M2.4 + World Trace #21

## Source and provenance
- Rendering source: successful M2.4 #230, `e4a1f88b02cd586affbb4cd672669b3fb70fbdf0`.
- Passive UEVR world trace: successful #234, `55fbe455271fbd328a8497d06a9238e769016c5f` (three source files, trace implementation copied unchanged).
- Integration workflow layers M2.4 visual and Present-epoch changes FIRST, compiles source shaders, then applies the UEVR trace anchors into already patched backend sources. It does not revert M2.4 to M2.3.
- UEVR mode ID6 = DuoView Mono M2.4; mode ID7 = TriView B43.
- Compatible research peer: VectorXR 0.20.1 Mono DynamicSmooth #36, commit `7f15a464ac0fa17a5d766c96cfc0ad4727943336`.
- Separate Cheeky NR companion: OpenNR Cheeky 0.6.3 build #84, commit `567f38810cf5e23b49d181d32527384e155ce12a`.

## Included from M2.4
- Two-axis depth conditioning, vertical taper default=2.
- Single-history B40 seam correction and corner projection update.
- Independent normal and wide per-eye sharpening, plus optional distance fade (OFF initially).
- M2.4 Present-epoch matching and 5-good-pair 200ms fine NGX ramp; **fine capture OFF by default**.
- Scale diagnostics and existing v208d / B43 lifecycle and VRAM safeguards.

## Included from UEVR World Trace #21
- Bounded game tick, render, pose and submit events, 131072 record rolling ring.
- Optional automatic timestamped CSV flush every 20s and after OpenXR session teardown.
- Enable `UEVR_WORLD_TRACE21=1` in `%LOCALAPPDATA%\VectorXR\framegen-research.txt`.
- Trace starts disabled and should not change rendering or runtime frame policy.

## Validations
- Strict source patch anchors and unified source-contract checks.
- M2.4 numeric/FXC shaders + CPU/D3D12 WARP and pinned backend compatibility tests from #230 retained.
- Exact TriView B43 shader checks retained.
- TriView Edge V2 WARP reference can fail on CI despite all other tests passing; preserve actual status in `TRIVIEW_EDGE_V2_TEST_FAILED.txt` and do not claim it passed when it didn't.
- CI success does NOT imply headset-tested. Test both ID6 and ID7 with tracing OFF/ON.

## First headset validation
1. Back up working UEVR/VectorXR installs and launch this ZIP's UEVR frontend.
2. In DuoView ID6, fine NGX depth OFF, standard Mono first; synthetic stereo at previously validated 0.9 strength / 0.25 m near / 0.25 sharpening.
3. Verify M2.4 2D conditioning, wide-only mode, seam corners and distance-fade OFF/ON, before combining with other tools.
4. In TriView ID7 verify visual parity with B43 and safe runtime reset, crop resize, save reload.
5. Install VectorXR #36 separately. Copy only research A preset at first. Enable UEVR trace and test 2-3 minutes; inspect independent UEVR and VectorXR CSVs. Repeat B/C/D only after A is sound.
6. Cheeky #84 should be tested after UEVR and VectorXR baseline. Use NR before SR; Duo fovea only or Tri both foveas, according to selected UEVR mode.

## Limits
- M2.4 Present epochs are not proof of source-frame identity; fine depth stays OFF.
- Timing CSVs record submitted OpenXR frames, not actual PSVR2 display scanout.
- Trace overhead requires real-world headset measurement.
- This package is one build supporting BOTH DuoView and TriView; the two separate prior builds are retained as rollback.
