# Stereo Quad Views — Build 44 Native Stereo Fix

ID7 renders left/right context views at reduced resolution and left/right focus
views with cropped frusta, then composites a distinct image for each eye.
It uses ordinary stereo OpenXR submission; runtime quad-view support is not
required. The supported target is STALKER 2 (UE5.5), DX12, OpenXR.

Build 44 starts from the accepted Build 40 source
`7486fc59890b14673cd50770b0dafeb692576716`. It adapts the Native Stereo Fix's
independent source construction/rendering and viewport display-gamma behavior
to four engine-owned targets. The original two-source Native/DuoView renderer
remains separate; ID6 and its source files are unchanged.

Each draw freezes the target set, stereo pose, projections, gaze and settings.
The compositor reads four distinct source textures. A quartet is eligible only
after all four exact target RHI tails execute for the same frame; duplicate,
missing, stale or aliased owners cannot authorize submission. A first new write
to reused targets invalidates the older unsubmitted quartet.

The existing crop geometry, gaze controls, fixed-center option and focus-only
Glamarye sharpening are retained. Default focus is 50% × 50%; context resolution
is 20% per axis. Sharpening defaults to 1.0, with zero bypass. Source targets
retain the full atlas extent to preserve engine view rectangles and projections.
This increases target memory usage and requires in-game performance measurement.

Install the compiled Windows ZIP in a separate folder. See `READ_FIRST.txt` for
the interior-lighting comparison and checks for stereo depth, FOV, gaze, loading,
mode changes and sustained frame delivery. Source archives are not installable
UEVR packages.

Diagnostics: 0 blended, 1 context only, 2 focus only, 3 synthetic source colors.
Synthetic colors prove compositor mapping only. Windows compilation, WARP pixel
checks and ownership tests cannot establish headset lighting parity or stability.

The nominal rectangles cover 29% of ordinary native-stereo raster area at the
default settings. This is a pixel-count calculation, not a GPU-time measurement.

Based on Joey/praydog UEVR and the project's accepted DuoView/QuadView work.
The fused sharpening derives from Robert Jessop's Glamarye Fast Effects for
ReShade; see `GLAMARYE_LICENSE.txt`.
