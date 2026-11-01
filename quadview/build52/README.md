# Build 52 — automatic QuadViews 2.10 source-position diagnostics

Based on the original Build 51 source commit f4e086c and identical Joey/UESDK/frontend pins.
Research-only: never change camera poses, view rectangles, shader, eye output, or source scheduling.

## For Liviu
1. Inject this complete Build 52 package into STALKER 2.10 as with Build 51. Select Quad Views Stereo (ID7), debug mode 0. Let it render for ~15 seconds. No need to look in the headset or describe the image.
2. Exit the game and open Windows Run (Win+R), paste `%TEMP%`, press Enter. Find the most recent `UEVR_Build52_Diagnostics_<PID>.zip`. Send the ZIP, plus the ordinary UEVR.log if readily available.

## Automatic data
- Seven horizontal source strips, 8 rows each, at 3%,13%,25%,50%,75%,87%,97% of the image height. Collected from all four actual D3D12 source textures.
- P6 PPM images role_0 through role_3 (full source width, stacked strips).
- coverage_summary.csv: first/last visible pixels, counts in left/right half, in the *expected* Build51 view rectangle, and at zero-origin.
- coverage_tiles_64px.csv: spatial coverage every 64 pixels across each source.
- README.txt: real resource dimensions, DXGI format, source role mapping, original expected view rectangles.
- Existing UEVR hook traces continue recording constructor/state, four singleton execution, RHI owner/tail, source selection, and XR submission; include UEVR.log for those data.

## Limitations / fail-closed behavior
No ZIP means no compositor source was accepted for capture or the readback was unavailable. The existing UEVR log then becomes essential.
The scanner measures non-black pixels, not proof of full geometry correctness. A completely dark scene is ambiguous. Every source copy takes place after the existing compositor draw, and its resource state is restored before the normal end-of-frame transition.
A single GPU capture can introduce one frame of hitch and a few megabytes of staging memory; normal rendering logic is unchanged.
Capture is limited to 1 successful archive per process. Remove the overlay script and helper to discard the diagnostics after the regression is resolved.
