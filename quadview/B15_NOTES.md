# Tri-view B15 (Claude, 6 Nov 2026) - NOT headset-tested

Base: B14 (claude/triview-b14-20261106, a4bdb8b), headset-tested OK by Liviu 6 Nov 10:45 (autostart 10 s).
Branch: `claude/triview-b15-20261106`. One change only.

## Recenter / standing origin / standing height in TriView
- Symptom (HEADSET, Liviu 6 Nov): Recenter View, Set Standing Origin and Set Standing Height often do
  nothing, at random, with the menu button AND the keyboard key; leaves you "diagonally" centred.
  Never in DuoView.
- Cause (source-read of the generated backend): all "where is the head now" reads go through
  `OpenXR::get_current_view_space_location()` = pose-ring slot `internal_frame_count % 6`. ID7 renders
  its roles with their own frame numbers (N, N+1, N+2) and Joey's BeginRenderingViewFamily hook moves
  `internal_frame_count` to each. Only N gets a located head pose; with 3 frames per draw and 6 slots
  the role slots are never refreshed. Recenter runs on the game-thread tick between draws, i.e. on a
  pose that can be minutes old. Joey's Native Fix / DuoView copy the pose into their second slot.
- Fix: `update_poses` remembers the newest located frame; while the TriView renderer is active and the
  current frame is not that frame, the current head pose is the newest located one
  (`uevr::quadview::current_pose_frame`). Rendering does not read this path at role time; all other
  modes return exactly the same slot as before.
- Tests: `quadview-triview-current-head-pose` (portable + ASan/UBSan): with the old rule all 200
  simulated TriView draws read an outdated pose, with B15 none; one-frame and Native Fix patterns are
  unchanged. `test_triview_b15.py` checks the generated backend.
- Possibly also affected before (not reported): anything else that reads the current head pose on the
  game thread in TriView (e.g. head-based movement direction, UI placement).

## Headset test
1. Start as usual (saved ID7). Turn your body ~45 degrees, press Recenter (menu or key) 5 times at
   different angles: it should centre every time.
2. Set Standing Origin and Set Standing Height a few times: each should apply at once.
3. Quick check that everything else is as in B14.
