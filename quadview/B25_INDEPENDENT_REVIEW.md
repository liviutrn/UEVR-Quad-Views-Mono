# TriView B25 — Independent crash-lifecycle review (2026-11-06)

## Why B24 is insufficient
B24 passed production Windows CI and sanitizers, but passing compilation is not evidence
that a GPU/OpenXR/UE5.5.4 lifetime transition is safe. It still had:
1. An unconditional `wait_for_all_copies()` reaching `wait(INFINITE)` before
   checking all XR texture-context fences. A GPU hang could freeze restart.
2. OpenXR UI reset or `xrDestroySwapchain` failures could leave partial resources
   while normal runtime submission continued.
3. A missing native target manager was treated as `native_owners_retired=true`.
4. A successful-looking `initialize_openxr()` optional error was insufficient:
   upstream has paths returning nullopt while setting `loaded=false`.
5. B14's `m_triview_hold_set` was not explicitly released on leaving TriView.
   When ID7 draw stops, the ordinary per-draw reset can never release its last
   retained source-owner lease. This could stall or invalidate retirement.
6. Async `pre_acquire` of XR images remained possible while the restart was draining.
7. Stale native source logs did not distinguish D3D12 device, allocation generation,
   and render target identity mismatches.

## B25 changes
- Release the B14 held source-owner lease and reset its resize gate at the GT
  rendering-method commit, after the existing engine tail retirement check.
- Treat missing native target manager as UNKNOWN, not proven drained.
- Preflight all XR image acquisition counts and command fences without blocking.
  Only enter inherited `wait_for_all_copies()` when every tracked context is
  already retired; pre-acquire is closed while restart phase 3 is active.
- On irreversible partial UI/XR destruction failure, mark XR unloaded and refuse
  further rendering rather than continuing on uncertain resources.
- Check the actual loaded state after `initialize_openxr()` before reporting success.
- Add stale owner allocation/publication/reason logs, without skipping any
  previous safety checks or adding CPU/GPU work to steady-state success.
- Keep B23 depth/compositor shaders, all three physical native sources, original
  four logical roles, Native Stereo Fix, source reuse, and UI controls unchanged.

## Still not proved
- The precise 0x139 Arg1=3 kernel corruption driver/module is unknown.
- The crop-change minidump had NO logged new target publication or resize request.
  Do not claim the fovea-size BSOD was caused by allocation or fixed in B25.
- The pipeline still has kernel driver/UE texture lifetime unknowns. SteamVR and
  VectorXR Dynamic FG real-world headset interactions remain unverified.
- Native Stereo restart may remain blocked if a recorded NGX depth command has
  never submitted/completed, or an owned engine object fails destruction proof.
  This is safer than freeing an outstanding GPU object, but it is not functional success.
- `destroy_swapchains` is not a fully atomic OpenXR transaction on
  `xrDestroySwapchain` failure. Once any handle destruction succeeds it cannot
  be rolled back. The partial-failure path now stops VR rendering and requires
  game restart rather than risking a BSOD.

## Validation required before headset
- B25 exact-anchor application to final generated backend.
- B24 and B25 generated production-code source contracts.
- Windows x64 production DLL, matching frontend and debug symbols.
- Portable sanitizer/ownership and compositor WARP tests.
- Independent review of raw OpenXR session refs and UI lifetime under
  `VR::on_post_present()`, especially previously held m_openvr_mtx.
- After that: a normal TriView run first, one manual runtime reinitialization
  with FG disabled from session start, then (only if stable) save-reload with
  VectorXR Dynamic FG. DO NOT deliberately reproduce Windows blue screens or
  drag crop sliders rapidly as a test.
