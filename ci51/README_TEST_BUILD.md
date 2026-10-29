DuoView TRUE STEREO XR V1 - CI51 DLSS dual-depth reconstruction
EXPERIMENTAL WINDOWS TEST BUILD. Not yet tested in STALKER 2 / PSVR2.

Extract into a separate directory. Keep the validated DuoView installation.
Use STALKER 2 DX12, DLSS Super Resolution, DuoView rendering method ID6.
Enable synthesized stereo. This enables LEFT fovea / RIGHT periphery native
cameras and disables diagnostic parallax reversal. Keep world scale/stereo
baseline at its normal value; no exaggerated disparity is needed.

Actual rendering:
- LEFT: native high-resolution fovea + RIGHT-to-LEFT reconstructed periphery.
- RIGHT: native low-resolution periphery + LEFT-to-RIGHT reconstructed fovea.
- Right fovea starts from RIGHT depth and validates against LEFT depth.
  Invalid/mixed visibility uses actual RIGHT color, rather than stretching
  source background across a foreground object.
- Optional source foreground refinement restores fine observable LEFT detail
  with hardware depth testing; it costs additional GPU work.
- Depth jitter/subrects are separate from resolved native-color coordinates.
- Fovea crop is fixed 0.50 x 0.50; periphery scale defaults0.20, maximum0.499.

Main controls: synthesized stereo, periphery resolution, foveal density,
blend, sharpening and eye tracking. Advanced stereo quality contains:
- Depth visibility tolerance in UE units/cm (default1.0).
- Relative depth visibility tolerance (default1.5%).
- Foreground edge guard in source depth texels (default1.0).
- Preserve fine foreground (default ON); disable to compare GPU cost.
Lower tolerances/larger guard favor real RIGHT fallback over uncertain detail.
Sliders do not alter native eye separation or world scale.
Legacy stereo modes and DSV candidate controls are under advanced diagnostics.
DSV pins are not the production DLSS source selector.

Runtime checks:
1. Enable stereo; inspect the actual output status, not just requested mode.
2. Compare near NPC/weapon edges, a wall, thin poles, foliage and fast turns.
3. Compare foreground refinement ON/OFF with GPU timing in the same scene.
4. Test save/load, DLSS quality changes and ten stereo toggles.
5. Capture now under advanced diagnostics saves both actual DLSS input sets
   (depth/color/motion), native source colors and final double-wide output.
   Open VIEW_DLSS_CAPTURE.cmd. Keep the WHOLE capture folder and UEVR log.
6. Disable synthesized stereo to compare the previous Mono composition.

Capture/identity limits:
- A producer RHI boundary associates guides with the immutable color packet.
  Dimensions identify the expected role only within that packet. This is not
  an authenticated UE per-pass jittered camera identity. Missing/mismatched or
  ambiguous packet pairs return to Mono and log the decision.
- Late-created and late-injection feature identities are reported separately.
  Known non-SR NGX features are rejected. Unknown feature type remains explicit.
- Original NGX inputs are copied AFTER successful Evaluate in the documented
  NON_PIXEL_SHADER_RESOURCE state, then restored. DIRECT/COMPUTE producer
  snapshots are fenced before the direct compositor reads them.
- Motion vectors are captured with scale/flags/resolution metadata, but are
  not yet used for temporal image accumulation. No temporal ghosting fix or
  generated-frame claim is made.
- Unknown late-attach motion extents save the whole actual MV allocation.
- No method can recover high-resolution surfaces hidden from both real views.
- CI/WARP tests verify synthetic GPU fixtures, not the NVIDIA/game/headset.

Source baseline: Joey UEVR5ac7edc207866569334175e4ed8a7517971547f6,
Build61 recipe421398aa943f21b292cf2b3a51da5f39b3116015.
The final source and exact hashes are exported with the Windows artifact.
