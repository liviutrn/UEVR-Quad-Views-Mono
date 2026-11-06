# Tri-view B14 (Claude, 6 Nov 2026) - NOT headset-tested

Base: ChatGPT's B13 (`experiment/triview-b13-adversarial-20261106`, 3a3ed96), which is B12 + fixes.
Branch: `claude/triview-b14-20261106`. Workflow: `.github/workflows/triview-b1.yml`.

## Verdict on B12 and B13 (independent review, source-read of the replayed generated backend)
- **B13 is the better base.** Its four changes are correct and I found no regression in them:
  - Per-slot producer fences: right fix. The signal is queued on the submitting queue *after* the
    original `ExecuteCommandLists`, each slot's fence only ever rises (shared counter), slot reuse still
    needs fence completion + no compositor lease, abandoned recordings keep their textures in the
    graveyard. The leftover shared `fence_` is only an install gate (harmless).
  - Shader `previousF <= -0.5` guard: correct (real `f` is never below about -0.125). The B12 error was
    small (interpolation weight about 0.99 toward the valid sample), but the fix is right.
  - Autostart log: now truthful. The state machine itself was already sound: `request(Native)` while
    Native is active clears the pending request (`Selection::request_locked`), and stage 2 waits for
    `!pending()`.
  - READ_FIRST: now accurate.
- **B12 depth-march maths: verified.** Re-derived: eye ray `t + l*d` seen from the centre camera
  lands at `uv_inf + 0.5*(ax, -ay)*(t.xy - d.xy*t.z) * s` (s = inverse depth), the same as the shader's
  `k`. Inverse depth `(C*d - A)/B` is right for UE reversed-Z (finite and infinite far). The eye-origin
  basis (OpenXR -> UE view axes, z flipped) is right. B14 now *tests* this on the GPU (below).

## B13 headset evidence (Liviu, 6 Nov 09:39-09:45, log + snapshot)
- Autostart worked but took about 28 s: it waited for Native Fix state *Active*, which STALKER 2 never
  reports (Joey's exact STALKER pair path does not call `note_native_stereo_frame_packet_consumed`), so
  it always ran into the 25 s timeout. The fix sat in PairReady from 09:39:17.
- FOV and seams: "perfect". Gaze: like DuoView. Depth used all session (10,930 of 11,245 copies).
- 09:42:43: four full-size 8120x3228 targets were built (+620 MB VRAM for about 20 s). Cause not yet
  known: probably "Compact source textures" switched off (asked).
- Crash 09:45:39: the log stops mid-line about 30 ms after a set with 3200x1792 foveas was published.
  VRAM was 8.1 of 9.8 GB budget before. Main suspect: out of video memory; not proven (game log asked).
  Each size change in this log made one build, so B14's resize gate would NOT have prevented it.
- Recentering (UEVR recenter / origin / height) reported unreliable for a few builds: not investigated
  in B14; needs isolation (Native Stereo vs ID7, same build).

## What B14 changes
1. **One build per settled size change** (`ResizeGate` in QuadViewGeometry.hpp). B12/B13 started a new
   four-texture build on every 64 px step of a slider. Each build allocates four Kismet render targets,
   and retired ones are only freed by Unreal's garbage collector (about once a minute); every new view
   size also makes Unreal and DLSS allocate buffers for that size. So dragging the periphery slider
   stacked up VRAM (estimate: tens of MB per step at 3.8k, plus engine/DLSS buffers; not measured).
   B14 keeps drawing with the current set while the wish changes, asks for ONE build once the sizes
   are unchanged for 0.4 s, keeps at most one build in flight, and knows the sizes of each set it asked
   for. A world change or mode switch drops a pending request.
2. **No legacy-path frame when the new set appears mid-frame.** The draw read the published set three
   times (size hold, compact selection, after `ensure()`). The new set is published from another
   thread, so a publish between those reads left the frozen layout without a matching set and that one
   frame fell back to the legacy family path (the path the B11 resize crash was attributed to; cause
   not proven). B14 reads it once per draw (`m_triview_hold_set`) and, if a new set appeared in
   between, finishes the frame with the held set (still owned; it retires through the fenced owner path).

3. **Faster saved-ID7 start.** The warm-up now accepts Native Fix PairReady or Active, held for 2 s
   (was Active for 3 s, unreachable on STALKER 2). Expected: about 10 s from the warm-up start
   (about 4.5 s to PairReady, 2 s hold, about 3.5 s for the ID7 switch) instead of about 28 s.

## New tests
- `quadview-depth-warp-ground-truth-stereo` (WARP, real shader): card at 30 cm in front of a wall at
  10 m; both eyes must sample the exact periphery point their own ray hits within 1 texel. Two control
  passes (warp off, sign flipped) must FAIL the same check (the CPU reference misses by 6.8 and 17
  texels), so the test can see a wrong warp.
- `quadview-depth-warp-scene-reference` (portable, also under ASan/UBSan): the same scene against a
  line-by-line C++ copy of the march: error < 0.00001 texel.
- `quadview-settled-single-build-resize` (portable, ASan/UBSan): slider drag = 0 builds while moving,
  1 after settling; in-flight build kept; world change drops it; timeout.
- `test_triview_b14.py` (generated backend): one published-set read before the layout freeze, all
  build requests through the gate, held set same-world only, autostart waits for PairReady|Active.
  Fails on the B13 tree.

## Still open (not changed, no evidence to act on)
- NGX depth state at Evaluate is still assumed NON_PIXEL_SHADER_RESOURCE (NVIDIA's documented input
  state; B11 ran about 18k copies in the headset without a crash). Only a D3D12 debug-layer session
  would prove it.
- Depth is the newest submitted copy (<= 250 ms), not frame-matched to the colour packet.
- If UEVR "Enable Depth" is on and you go TriView -> Native Stereo in one session, the missing OpenXR
  depth swapchain makes `[VR] OpenXR: Trying to copy to swapchain ... doesn't exist` repeat in the log.
  Restart the game for Native Stereo depth.
- Every resize still rebuilds all four textures (also the unchanged fovea ones) and the unused
  right-context role is still allocated (small at TriView sizes).
- Shader cost (25 depth loads per periphery pixel outside the fovea) is not measured.
- No FPS or VRAM measurement exists for B12, B13 or B14.

## Headset test (Liviu) - stop at the first problem
1. Saved ID7, fresh game start. Within about 10-15 s: both eyes sharp in the centre, no black screen. The log
   should show `[TriView][Autostart] ID7 committed`.
2. Look at your hands/gun near the edge of the sharp area: are they doubled? Close one eye at a time.
3. Turn "Show periphery depth" on for 2 s (grayscale = depth works; magenta checker = no depth), then off.
4. ONE periphery resolution change: drag the slider, release, wait 2 s. The log should show ONE
   `Published four independent UE5.5 source targets` line for it. Note VRAM before and after.
5. Report: fps at one fixed spot, VRAM, anything odd, and the UEVR log.
For a crash or BSOD: Windows stop code, LiveKernelEvent folder, NVIDIA driver version, UEVR log, minidump.
