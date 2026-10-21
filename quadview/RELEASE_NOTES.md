# Build 45 — four-source Native Stereo Fix

Fixes Build 44's native-dispatch bootstrap deadlock: dispatch now validates
constructed views before the Unreal callback, while output still requires
callback-authenticated family ownership. Adds a regression for that ordering
and throttled native-dispatch diagnostics. Build 44 submitted a warmup frame,
then stopped before invoking the callback that its guard required.

Built from the accepted Build 40 source at `7486fc59890b14673cd50770b0dafeb692576716`.

The ID7 native path isolates left/right context and left/right focus in four
engine-owned outputs. The compositor samples each source independently,
including focus sharpening. Publication requires a coherent quartet from the
same frame and target generation. Build 40 gaze, crop geometry and stereo
projection behavior are retained; the ID6 DuoView source is unchanged.

The full atlas extent is retained for each target to preserve existing engine
view rectangles without introducing undocumented view-layout modifications.
This increases render-target memory consumption; performance must be measured
in the game rather than inferred from pixel counts.

Validation includes portable frame/history and asynchronous-delivery contracts,
Windows shader compilation, four-source WARP compositor checks, the original
compatibility suite, and the Windows backend/frontend build. The accompanying
CI evidence records their actual outcomes. No automated test establishes
STALKER 2 lighting parity, headset stability, or headset performance.

Compare shadowed interiors against Native Stereo Fix, DuoView and Build 40,
including the previously reported left-eye focus/periphery shading mismatch.
Also check FOV, gaze, mode transitions, loading and sustained frame delivery.
