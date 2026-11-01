# Tri-View Stage 1: decision (1 Nov 2026, Claude, lead builder)

Goal (Liviu): fastest correct tri-view test build, built FROM Joey's Native Stereo + Native Fix, Joey-style.
Branch: `claude/triview-stage1-20261101` (from v207 `4020a44`). Workflow: `.github/workflows/triview-stage1.yml`
(the v207 workflow renamed; it is the only workflow that fires on this branch). Line numbers are the v207-patched
`src/mods/vr/FFakeStereoRenderingHook.cpp` (Joey `5ac7edc` + v207 chain) unless noted.
Labels: [source-read] = checked in the real code; [estimated] = reasoning, not measured.

## 1. How Joey's Native Fix makes its per-eye renders (UE < 5.7 generic path, STALKER 2 UE 5.5.4)
- `GetDesiredNumberOfViews` returns 2 once the Native Fix hooks and capture target are ready (31095-31307). [source-read]
- UE builds each view itself: camera `calculate_stereo_view_offset` (30161), projection
  `calculate_stereo_projection_matrix` (30667), rect `adjust_view_rect` (30062; under Native Fix both eyes keep x = 0).
  View states: on STALKER with Native Fix, Joey runs the normal LocalPlayer bootstrap (the "lazy synced view
  states" path 5739 is only for Synced AFR); UE5's `CalcSceneViewInitOptions` adds a view state per view index
  lazily, so view 2 gets its own. [source-read Joey; UE part from engine source knowledge, not in this repo]
- The constructor hook relabels the SECONDARY eye as PRIMARY while it is built (same pass, forced on STALKER,
  23280-23345). Pass for index 2 = PRIMARY (`view_index % 2`, 31313). [source-read]
- `begin_render_viewfamily_real` (24691) proves exactly one PRIMARY/SECONDARY pair in a family with exactly 2
  views (25354-25484), then renders the SAME family twice: views=[left], count 1, main target (26695-26702);
  then views=[right], count 1, target = capture, after `scene->decrement_frame_count()` (26727-26850); then
  publishes one packet (26881). A scope guard restores views, count and target (26235). [source-read]
- D3D12: Joey copies main-target left half + capture into the double-wide XR image (`pre_render`,
  D3D12Component.cpp 3730; branch 5476-5485). Main target is 2W x H (38525); Native Fix uses only its left half. [source-read]

## 2. Root cause candidate for the 2.10 breakage of Build 40/51/B1-B3
Joey's three stereo hooks keep static "index 2 means one-based eyes" flags (30078-30091, 30192-30236, 30829-30848).
The first view index 2 sets `index_was_ever_two` forever: from then on view 0 returns early from
`calculate_stereo_view_offset` (30222, no head/eye pose) and eyes 0/1 swap projections. [source-read]
Whether this is exactly what broke the old builds is [estimated]; Tri-View avoids it by construction.

## 3. How the third render is added
- New rendering method ID 7 "Tri-View (Experimental)". `RenderingMethodSetting::value()` reports 0 for ID 7, so all
  Native Stereo code runs unchanged; Tri-View code checks the raw ID. Modes 0-6 unchanged. Active only on
  STALKER 2 + D3D12 + OpenXR (same gate as DuoView ID 6). Forces Native Fix on (same pass) and Joey's opt-in
  STALKER pair experiment off.
- `GetDesiredNumberOfViews` returns 3 (2 when the menu switch "third view" is OFF), only after all of Joey's
  Native Fix readiness checks and while the HMD is active.
- Index 2 is handled BEFORE the legacy statics in all three hooks:
  camera = midpoint of the two eye positions Joey computed this frame (after Lua mods), left-eye rotation;
  projection = left-eye projection widened to the union of both eye frusta (parallel eyes, PSVR2);
  rect = (W, 0) in the free right half of the main target, size = periphery scale x union size (default 0.5).
- Eyes 0/1: rect W/2 x H/2 at (0,0); projection cropped to the fixed centre 0.5 x 0.5 window (same math as v207's
  headset-proven DuoView crop, DuoViewGeometry.hpp 98-111). [source-read]
- `begin_render_viewfamily_real`: view 2 is hidden (count 3 -> 2) before any Joey validation, so his proven pair
  logic sees exactly his two eyes. After his secondary render, view 2 is rendered once the same way (frame-count
  decrement, singleton family) into the main target. Count 3 is restored on every exit (the engine deletes 3 views).
- Composite (new D3D12 pass, replaces Joey's copy only for ID 7): each eye = periphery remapped into that eye
  (affine, parallel eyes) underneath, own fovea on top, 8% feather. Same XR pose and submission as Native Stereo.
  Third view OFF = foveas on black. Any rejection = Joey's copy. One colour encoding for all images (typeless
  adopts the typed one), so colours pass through unchanged like Joey's copy.

## 4. Review fixes on the first draft (this session)
1. Removed an extra OpenXR pose-slot clone before the third render: the frame-count decrement already gives
   view 2 the eyes' frame number and pose slot; the clone wrote a future slot for nothing.
2. Compositor colour encoding: the XR image is requested as sRGB but may come back typeless; the draft then
   rejected sRGB-typed sources (silent fallback to Joey's copy = black edges). Now follows the sources' encoding.
3. Third view requested only while the HMD is active (avoids a 3-view family reaching the renderer unsplit).

Independent review (Sonnet, fresh eyes) found, and these are fixed:
4. CI compile break: windows.h min/max macros vs `std::min` in TriViewGeometry.hpp (NOMINMAX + `(std::min)`).
5. The third render is the first view of its renderer call, and UE clears the whole family target for the first
   view unless the family is marked `bAdditionalViewFamily` (engine-source memory of ScreenPass
   `CreateViewFamilyOutput`, [estimated]; Joey marks the same flag for his UE5.7 clone, 913-950 [source-read]).
   Without it the third render would erase the left fovea. Fix: set the flag only for the third render. Its offset
   follows UE's layout `uint32 FrameNumber; uint64 FrameCounter; bool bAdditionalViewFamily` (Joey's UE5.7: +0xA0 /
   +0xB0) from Joey's discovered FrameNumber offset, and is used only after FrameCounter is proven by two exact +1
   steps between frames and the flag reads 0. Otherwise the third render is skipped (black edges, foveas intact,
   log line; the flag position and neighbouring bytes are logged once for checking). The eyes' frame number must
   advance every frame: if it stalls after a third render, the decrement is dropped (the engine then does not
   advance additional families); if it still stalls, the third view switches off. (Second review, Sonnet.)
6. View index 2 is claimed only while Tri-View is ACTIVE (not merely selected in an unsupported game).
7. Colour: a typed sRGB XR image with typed UNORM sources (or the reverse) cannot be recast in D3D12; the shader now
   undoes the hardware sRGB conversion instead of rejecting (reject = no Tri-View image at all).

## 5. Checks before headset
CPU geometry test (layout, crop, union, eye->periphery map) runs locally and in CI; WARP pixel test of the real
compositor in CI; local replay of the full v207 chain + this patch; independent review before push.

## 6. Speed expectation [estimated]
From Liviu's numbers (~7 ms per render family; Native Stereo 24 fps at 3.8k x 3.1k): Tri-View = 3 families but
~0.77 eye-areas of pixels instead of 2 -> about 28-32 fps at 3.8k (+15-30%). Old broken B3 measured ~28-30.
If the headset shows < 24 fps at 3.8k, the extra family costs more than modelled.

## 7. Headset test 1 (build 0bce657, 1 Nov 21:00) [headset-verified]
Both foveas render and look right, fps better than Native Stereo, periphery black. Log: every frame
`Third view skipped: additional-family flag not proven (readable=true steps=2 flag=4)`.
- FrameNumber is at +0xAC; FrameCounter at +0xB0 stepped by exactly 1 (proven), so the guess "flag = FrameCounter + 8 = +0xB8" was a UE5.7-era
  layout and reads 4 on UE 5.5.4. The safety gate worked: nothing was written, foveas stayed intact.
- Joey's NASCAR25 table (UE 5.5.4, `NascarHookCompatibility.hpp` layout25, "independently checked against the runtime image and source")
  has `family_size 0x1B0, family_additional_offset 0xC8`. His UE5.6.1 table has 0xB0 (= the 5.7 position). [source-read]
- Build 2: default flag offset = 0xC8 (200), written only if it currently reads 0, restored after the render; the menu field can name another
  offset or -1 (untouched). FrameCounter proof dropped (it only served the wrong guess). A hex dump of family bytes +0x9C..+0x12B is logged
  once, so 0xC8 can be checked against the real layout. Whether the flag is needed at all is still [estimated]; test 2 shows it:
  left fovea must stay sharp while the periphery appears.
