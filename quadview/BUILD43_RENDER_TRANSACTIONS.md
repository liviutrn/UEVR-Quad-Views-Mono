# Build 43 development — staged Native Stereo renderer isolation

Baseline: Build 40 commit `7486fc59890b14673cd50770b0dafeb692576716`.

**This is an experimental renderer integration candidate; it is NOT the complete four-target Native Stereo Fix.** It does not yet prove the observed Lumen and brightness problems are corrected. No PSVR2 headset validation has been performed.

## Implemented on this branch
- Separate native Unreal renderer dispatch for context L/R and focus L/R, with four original `FSceneView` / scene-state identities preserved.
- Strict generation/frame/target/scene pair-ledger: the first render callback cannot publish the atlas; only the second paired callback is eligible to own the tracked RHI completion.
- Exact producer identity validation, 4 unique source views and safe restoration of the engine family view array.
- GUI toggle `QuadViewNativeStereoPairExperiment` defaults OFF. OFF executes the exact Build 40 single-transaction path.
- Regression assertions for pair-ledger ordering, duplicate rejection and reset.
- Windows CI compiles the original pinned Joey backend from source using an existing, authorized UESDK credential on the MUSE build host; does not copy secrets.

## Limitations and risk
The two engine dispatches currently target the same atlas. Unreal may clear or invalidate context pixels or render auxiliary effects differently during the second dispatch. The RT source ledger is conservative, but passing unit tests cannot prove Unreal preserves both images. Four individually isolated generation-owned render targets, with safe GPU copy/resolve and native-exposure/Lumen parity, are **not yet implemented**. Do not label this candidate a complete Native Stereo Fix.

## First headset A/B validation
1. Keep the tested original Build 40 separate. Never overwrite it.
2. Install this candidate into a separate UEVR directory. Set Quad Views ID7; leave experimental pair toggle OFF; confirm Build 40 baseline behavior.
3. Enable `QuadViewNativeStereoPairExperiment` while at a reproducible scene, then compare left and right periphery against focus and against normal native stereo and DuoView. Repeat in shadowed interiors.
4. Check startup/re-toggle black frames, source held/failed counts, 1% low frame time, FOV and gaze stability.
5. Switch OFF immediately if either context disappears or image/rhythm degrades. Attach the game log and paired screenshots for source and GPU analysis.

A real final Build43 release requires four independently verified render targets and headset evidence that Lumen/brightness, FOV, gaze and source delivery match or improve Build 40.
