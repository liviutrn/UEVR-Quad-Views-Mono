# DuoView CI74: stationary jitter sequence recorder (EXPERIMENTAL)

Adds an in-game button under **DuoView > Stereo and quality > Advanced stereo and capture diagnostics**:
`RECORD 2s stereo jitter (compact ZIP)`.

After pressing, close the VR menu during the 3-second countdown, then keep your view fixed on a jittering edge. Recorder queues up to **64 consecutive genuine rendered frames** over 2 seconds. Each frame contains four native-pixel crops: final XR LEFT and RIGHT 512x512 (central field), LEFT source fovea and RIGHT periphery 256x256. The final eye crops are taken **after the actual stereo compositor** and before OpenXR submission. It does not capture SteamVR motion-smoothing output. Stereo render/shader code and the older one-frame raw gallery remain unchanged.

Readback buffers are allocated on the Present preparation path (not within the XR copy callback). The callback records bounded GPU copy operations. Each frame has a post-submit queue fence; the WIC JPEG encoding and the ZIP writer run on a background thread after the sequence stops. No GPU fence wait or JPEG encoding takes place in the XR callback. The fixed allocation limit is ~160 MiB per 64-frame session, with max ZIP size **18 MiB**. If exceeded, the ZIP contains fewer frames and `truncated_by_size=true`. If a candidate source is unsupported, that frame is rejected. Status and output path display in the game menu.

Output: `%TEMP%\UEVR_DuoViewSequences\sequence_...zip` with JPEG patches + `manifest.json`. Manifest records source frame, requested/effective stereo, camera positions/rotations, frozen color projection matrices, depth serial selections, individual file crops and timestamps. It reports that source depth eye/frame authentication is NOT proven. This initial recorder does NOT export raw NGX depth or motion vectors; the first objective is to quantify *observed output jitter vs native source jitter*. It cannot diagnose every possible depth reason or headset-side reprojection artifacts.

**Safety:** This is an experimental instrument, not headset-validated. Run only in a copy of the experimental UEVR install. Requires a working stereo path and BGRA8/RGBA8/R10 XR/source formats, source rectangles at least 256px and XR eyes at least 512px. Unsupported formats fail cleanly. GPU/readback overhead occurs only during the recording window. Don’t judge real-time performance during capture; compare stereo quality before/after recording.

## Build

`python workspace/ci74/apply.py backend` **after CI73** and before full CMake build. CI74 is deliberately additive and does not change shader compilation logic.

## Cloud analysis

Use `ci74/analyze_sequence.py sequence_...zip --out report.json` (requires numpy and Pillow) to measure synchronized input/output temporal activity and edge instability. This diagnostic does not assert physical stereo accuracy or prove jitter source; camera/gaze or scene changes can contaminate metrics. Missing frames are reported.
