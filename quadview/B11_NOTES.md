# Tri-view B11 (Claude, 5 Nov 2026): depth reprojection ON, ID7 cold start, proof snapshots

Base: ChatGPT B10 checkpoint cb42719 (B8 features + B9 startup/menu fixes + B10 exact depth geometry).
Status: CI only until the headset test. NOT headset-verified.

## What changed vs B10
1. Depth identity: B10's thread-local "owner scope" around the retained RHI callback could never see
   NGX Evaluate (it runs elsewhere), so capture stayed disabled. B11 identifies the periphery by its
   DLSS output size. make_layout() now guarantees that size is unique: if the context would be within
   6 % of a fovea size, it is made 7 % smaller than the fovea (same aspect and FOV). Matching tolerance
   is 3 % / 4 px. Unknown NGX feature handles (created before our hooks) are accepted.
2. Ordering: the copy is recorded on the game's DIRECT list before Evaluate; it is used once that list
   was submitted (ExecuteCommandLists hook). The compositor submits later on the same GPU queue, so the
   GPU orders them. Slot reuse still needs the producer fence and no compositor lease; a copy whose list
   never reached the queue is reused after 2 s. The game's ExecuteCommandLists is no longer serialised
   behind our mutex, and the global command-list Reset hook (B10) was removed (CPU cost on every list).
3. Reprojection is ON by default (new setting key). Missing DLSS jitter = zero (sub-texel), no longer
   disables the warp.
4. Cold start: on STALKER 2 UE5.5.4 DX12 stalker2_uses_lazy_synced_viewstates() is true unless Native
   Stereo Fix is active, and ID7 reports Native Fix OFF, so the LocalPlayer two-view bootstrap never ran
   (black headset; the user's workaround ran it via Native Stereo + Fix). apply_triview_coldstart.py makes
   ID7 count as Native Fix for that policy only until the bootstrap settles (m_fixed_localplayer_view_count),
   then ID7 continues on the same lazy path as after the manual workaround. DuoView ID6 solved the same
   issue by reporting Native Fix as active (apply_stage234.py).
5. Proof from the game:
   - `[TriView][Depth]` log line every second (hooks, DLSS calls, sizes, copies, submitted, used, skip
     reason, jitter, warp state). `[TriView][ColdStart]` logs the bootstrap transition.
   - Snapshot: automatic once 25 s after ID7 is selected, and a menu button. Writes the final double-wide
     eye image, the three source renders, the periphery depth (.dds) and an info .txt (layout, crops,
     homographies, depth geometry, shader constants) to `<UEVR game folder>/triview_snapshots/`.
     Readback heaps live in system RAM, files are written on a background thread.
6. MSVC C2512 in DepthGeometryTests.cpp (std::source_location default argument) replaced by a __LINE__ macro.

## Verified before the headset
- Portable suite 21/21 on Linux, also under ASan/UBSan; new tests: unique context size over a settings
  grid, 3 % matcher, equal-size nudge.
- Full overlay replay on pinned Joey 5ac7edc + frontend 60be4b0 (FXC stubbed), generated-source contracts
  (test_triview_depth_live.py, incl. cold-start policy).
- MinGW cross syntax check of QuadViewD3D12.hpp, QuadViewNgxDepth.hpp and the WARP test.
- WARP pass 20 now also records a snapshot under the D3D12 debug layer and checks the 5 images + info.

## Not verifiable offline
NGX parameter availability in this game, the real depth resource state, eye-origin sign in game units,
cold-start runtime behaviour. The log line + snapshot answer these from one headset run.
