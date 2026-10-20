# Quad Views Stereo ID7 — October 20, 2026 experimental continuation

This is the canonical development branch in the **Quad Views repository**. The prior OpenNR branch was used only as a Windows CI staging copy. QuadView code matches `liviutrn/OpenNR@966fb9b2a8824078b75c7ca097f6d9c890a7b2dc` (the most recent diagnostic snapshot checked).

This remains a candidate, **not a stable/headset-verified release**. Build 32 showed native stereo output but crashed; the original RenderThread null-parent access violation has not been proven repaired. The included PSVR2 gaze, frame stability and fused Glamarye changes require Windows builds, shader/WARP checks, runtime frame continuity and STALKER 2 in-headset confirmation.

Experimental branch changes do not alter main, stable DuoView v182, DuoView v186.1 or UESDK. The branch workflow uses Windows GitHub Actions; tests require original pinned SDK access through a repository secret. If secrets are unavailable, CI will stop safely rather than bypass SDK access control.
