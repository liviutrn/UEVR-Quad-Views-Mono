# DuoView Mono v208d parity in TriView B43 — Phase 1
Date: 2026-11-12. Source-read; CI pending; headset UNVERIFIED.

## Source identity
TriView parent: claude/triview-b43-20261112 @ cc74589c91a254c26e597784b4b68062098ff7d7.
DuoView v208d: claude/v208b-sharpen5-vram-20261102
@ 9362b5edbe3e2c6b3fecf8842d4be14b097a9095.
Exact duoview subtree SHA: 3d5593a82ac13532989420b2e356b17602b1098b, checked by workflow.
Joey/UESDK/frontend pins unchanged: 5ac7edc/3cffbc8/60be4b0.

## Change scope
- Replaced old duoview/ subtree in one pinned tree operation, including
  shader, compositor, config, gaze back-off, VRAM functionality and tests.
- Complete v208d scripts run in original order after Stage 2-4 and before
  every TriView overlay: MPC, HUD, B48 alignment, B49 persistence, XYZ,
  v165, v205, v207, v208, v208b, v208d.
- No edits to TriView B43 shaders, compositor or overlay scripts.
- ID7 still the fresh-install default. For ID6 fresh settings: eye alignment
  ON at -1.5, SameImageBothEyes ON for mono VectorXR, SharpPeriphery OFF.
  Existing config values override defaults. Shared image ON means both
  eyes see identical Mono sharpening; per-eye sharpening requires OFF.
- Phase 2 focus lift, B43 sharpening and seam math deliberately deferred
  to next build after mode 6 parity is CI-checked.

## Validation
- Source subtree pin, guarded patch anchors, Build49 persistence and XYZ
  contract tests; existing TriView CPU/GPU suite, DuoView WARP, original
  UEVR compatibility and frontend rendering ID tests.
- Local patch replay not run: execution container cannot reach GitHub;
  GitHub Actions will perform the full guarded patch replay and compile.
- At most three headset checks:
  1. Is ID6's scale/HUD/FOV/shared-eye behavior like working v208d?
  2. Does 7->6->7 switch in game without black frames or a crash?
  3. Is TriView ID7 unchanged in appearance/performance?
