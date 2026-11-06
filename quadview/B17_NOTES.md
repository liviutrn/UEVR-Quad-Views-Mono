# TriView B17 — Three physical sources and original UI wheel fix

Parent: Claude's **B15**, branch \`claude/triview-b15-20261106\`. This branch does NOT apply B16.

## What changed

- TriView alone is selectable in the ID7 rendering method: the QuadView four-render
  toggle and full-size source toggle are removed from the **UI**. Existing settings
  keys remain recognized, but both selections are now forced to shared periphery
  and compact sources, regardless of persisted legacy values.
- Retain four **logical engine view identities** 0,1,2,3 required by Build51/B15
  family registration, OpenXR mapping and existing provenance checks. Do NOT
  remove this ABI or change frame identity.
- Allocate exactly three independent UE-owned physical colour render targets:
  slot 0 shared periphery, slot 2 left fovea, slot 3 right fovea. Slot 1 has
  zero extents, no holder actor, texture, RHI or native resource.
- Required-role validation masks (0x0d), native lifetime validation, renderer
  dispatch and binding ignore dormant physical slot 1, while still validating
  resource uniqueness for active slots.
- The existing D3D12 compositor still requires four descriptors. Shader slot 1
  aliases the already-owned source 0 *at descriptor binding only*. ContextSource
  remains 0 for both runtime eyes. No fourth colour buffer is allocated.
- Fail closed if synchronized shared-context projection unavailable. Do not
  render true QuadView or allocate a four-target fallback.
- Keep B14 resize gate and GPU retirement path as-is (no B16 timing change).
  Unchanged per-role targets are NOT yet reused across resize generations.
- Keep exact B15 recentering pose correction and B7/B11 depth reprojection.
- B9 diagnostics child is the same size, at the same place. Adding
  \`ImGuiWindowFlags_NoScrollWithMouse\` prevents that child from capturing the
  parent's mouse wheel; no second scroll UI, new controls panel or layout shifts.

## Validation scope

- \`TriViewThreePhysicalTests.cpp\` verifies exactly 0,2,3 are physical; rejects
  an occupied slot 1, invalid roles, wrong dimensions, duplicates and generation
  mismatches.
- \`test_triview_b17.py\` checks invariants in the *generated* backend after
  the complete B15 overlay chain.
- Production Windows compilation, existing portable tests, production compositor
  shader/GPU tests and packaging remain required by CI.
- CI passing does NOT mean headset validation. No measured VRAM/FPS performance
  claim or BSOD fix is made. The suspected resizing crash and right-eye flashes
  still require runtime diagnostics and a crash dump.

## Risk and test priorities

1. Native Stereo Fix bootstrap/initial TriView start without a mode toggle;
2. left/right fovea + shared mono reprojection, including DLSS depth;
3. mouse wheel over diagnostics and over adjacent original menu controls;
4. repeated resolution/crop changes at safe sizes, observing GPU/CPU lifetimes;
5. config save/reload, B15 recenter and both-eye presentation.

Do not deliberately stress maximal crop/resolution until GPU safety is
independently tested. Any blue screen warrants stop code/minidump analysis.
