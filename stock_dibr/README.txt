Joey stock DIBR test package
============================

This patch builds on the pinned Joey UEVR backend commit
5ac7edc207866569334175e4ed8a7517971547f6, with UESDK
3cffbc82429b6165ceec2714f0f0d9ae48f55596 and matching injector frontend
60be4b0f9a646109fd9fdf448bacd41477234091.

The patch uses Joey's existing Synthetic DIBR rendering method IDs only:

  3  Synthetic Stereo (DIBR, Experimental)
  4  Synthetic Stereo (DIBR Single View, Experimental)

It adds no rendering-method IDs and contains no DuoView implementation.

Test setup
----------

1. Extract this package into a new, separate test folder. Keep any known-good
   UEVR installation untouched.
2. Launch STALKER 2 in DX12 with the OpenXR runtime selected in the injector.
3. In UEVR, turn Native Stereo Fix off and turn Use Same Stereo Pass off.
   Select method 3 first. Enable “Enable DSV/RDG Depth Capture (Experimental)”
   in the DIBR section.
4. Start with DLAA in the game. After the DIBR depth capture and output look
   stable, repeat the test with DLSS enabled and note any change in the
   reported depth dimensions or behavior.
5. To check the single-view path, select method 4. The UEVR menu must show
   “Single-view status: active”, and “Suppressed engine-view frames” must keep
   increasing while the game renders. Both readings are needed to confirm
   that the one-view path is running.

The CI workflow builds the depth-policy checks, Windows WARP checks and the
injector package. Joey's unchanged 41-test compatibility suite passed in the
previous full run 40198571708. Current format corrections use the actual-format
production GPU test rather than repeating that unchanged suite. These checks do not
verify STALKER 2 runtime behavior or headset stability. This package has not
been verified in-game unless separate runtime testing is recorded.

Revision 2: first headset-test corrections
------------------------------------------
The first test produced no depth and showed a misaligned duplicated-eye
fallback. Revision 2 preserves original two-view stereo during warmup,
hooks binding/viewport/reset methods on all queried D3D12 command-list
interfaces, and samples the observed valid viewport inside reused or padded
depth allocations. Its log reports exact rejection categories and binding
hook counts. DIBR tuning sliders affect the image only after synthesis is ready.
No game input code was changed.

The actual format-19 depth/stencil resource is now accepted and sampled using
its format-21 depth-plane SRV. Earlier documentation misidentified format 19
as plain R32_TYPELESS (which is format 39); that caused valid depth to be rejected.
The GPU test now uses padded R32G8X24_TYPELESS / D32_FLOAT_S8X24_UINT resources,
including full depth-plane copy and live frame updates, under the debug layer.
