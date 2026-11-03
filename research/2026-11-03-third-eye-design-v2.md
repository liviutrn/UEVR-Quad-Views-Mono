# Third eye, design v2 (2026-11-03) - status: DESIGN ONLY, nothing built from it yet

Why: TriView proof builds 1 and 2 (engine builds 3 views) render a correct third image but break head tracking.
Labels: READ = code read by a helper/me, INFERRED = not verified. UESDK (private) is not available locally.

## Finding
Joey's Native Fix path already renders the two eyes as TWO SEPARATE renderer calls (F:26480-26710) and
fails closed to the original render if the engine ever has other than exactly 2 views (F:25254, 25705, 26070).
Our builds made the ENGINE build 3 views (GetDesiredNumberOfViews=3, view index 2 hooks). That is outside
everything Joey validated (view index 2 also flips Joey's static index_starts_from_one / index_was_ever_two
in calculate_stereo_view_offset, adjust_view_rect, projection - READ F:29999-30018). We only guard it
with triview_owns_view_index_two(), which is a runtime flag (INFERRED weak point).

## Design v2 (third eye as a third renderer call, in Joey's own sequence)
1. Engine keeps exactly 2 views at render time (GetDesiredNumberOfViews returns 2, no index-2 hooks).
2. After the second-eye call, do a third call exactly like the second: set_render_target(third target),
   views={third view}, count=1, scene->decrement_frame_count(), render_secondary_view().
3. Third view = copy of eye-1 view data with its OWN FSceneViewState. State source: let the LocalPlayer
   replay allocate 3 states once (return 3 only inside post_init_properties, F:30846) and use state[2].  UNKNOWN: can a view's State be rewritten after construction (UESDK).
4. Pose: clone pipeline_states to +1 AND +2 (F:26524 only does +1) so the render thread never sees an empty slot.
5. Own capture target (copy of the existing scene-capture machinery: actor/texture/generation/snapshot).
6. Packet carries 3 captures and is published once after the last call, so one stale check covers all three (F:25966, 27388).
7. Delivery: keep our TriView D3D12 three-source compositor (already CI-tested, correct image); XR layer stays 2 views.

## Open items before building
- Can FSceneView::State be overwritten? (needs UESDK read in CI log or source access)
- Third target size must be accepted by D3D12Component (D:3600-3613 requires eye size).
- Rank-ordered break risks: pose slot +2, packet staleness window, view-state count, XR layer (see helper report).
