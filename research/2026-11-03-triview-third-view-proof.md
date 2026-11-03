# Third-view PROOF (Claude, 3 Nov 2026) - branch claude/triview-proof-20261103

Question (Liviu): Joey's Native Stereo + Native Fix works great on STALKER 2.10. Can a THIRD view be added with
exactly the plumbing of the second view? Nothing else (no crop, no periphery, no eye tracking) until that is proven.

## What the build does (PROOF toggle, default ON, menu: Tri-View - settings and status)
- Eyes are NOT cropped (windows 0..1, fovea = full eye): plain Native Stereo + Native Fix.
- GetDesiredNumberOfViews = 3 (S2-S6 mechanism, unchanged). View 2's FSceneView constructor receives an EXACT copy of the
  second eye view's init options: rotation matrix, origin, projection. Only differences from view 1: own scene state
  (own temporal history, engine-allocated), own render target, rect 2 px narrower (engine hooks recognise view 2 by its rect).
- View 2 is rendered after the second view with the same singleton-family steps as Joey's secondary render (frame-count
  decrement, own target at (0,0)); compositor (WARP-tested): left eye = view 0; right eye left half = view 1 (real),
  right half = view 2 tinted red (x 1, .35, .35), 2 px black seam. A broken or missing third view is visible at once.
- Reading guide: identical content + no trembling in the red half => a third view with second-view plumbing is possible,
  so the S6 tremble came from what was different (centre camera / union FOV / 0.5 scale / crop / state handling).
  Red half trembles or lags while the normal half is calm => the third-view mechanism itself (history, frame count,
  render order, target) is at fault, independent of geometry.

## Diagnostics
- [TriProof] log line (once per second + every 900th frame): view 2 clone origin, rect vs eye rect, scene-state pointers of
  view 1 and view 2 ("separate history" / "SHARED history"). Warns if view 2 is built without the second eye seen.
- Existing S6 [TriDiag] lines (armed once per second): ctor, projection/offset hooks, "third render" with FrameNumber,
  packet. Menu: frames with/without third view, skipped third views, composites/rejects, captures.
- Automatic TriView_Capture_N.zip (main, capture, periphery, xr): compare capture vs periphery images offline.

## Evidence labels
source-read + replayed + WARP/geometry tests: see PROGRESS.md. NOT headset-tested.
