# Build 198 — Global STALKER 2 First-Person FOV bypass

**Experimental, headset unverified.** Source branch: `experiment/duoview-disable-firstperson-fov-20261022`.
Base: DuoView v186.1 compositor, PSVR2 gaze, Native Stereo Fix and overlay-convergence implementation on existing experimental C++ source. Mode ID6 only. Modes ID0/ID5 unchanged.

## Mechanism

A STALKER 2 UEVR VR profile already sets the game material collection's `IsFOVEnabled` scalar to 0 through `CameraManager.FovMPC.Collection` before rendering. This disables the game's artificial first-person FOV treatment of meshes, unlike the obsolete `TanFOV` factor experiment.

Our C++ bridge uses the reflected Kismet material library calls to read/write `/Game/_Stalker_2/Materials/MPC/MPC_FOV.MPC_FOV -> IsFOVEnabled`. It runs on UE's `VR::on_pre_engine_tick` **once per game tick**, ahead of fovea and periphery capture, never in the XR copy callback and never with independently variable per-pass values.

The UI contains exactly one **Disable STALKER 2 First-Person FOV (both sources)** toggle (default OFF). The game-original value is saved when activating, reapplied to 0 if ADS/game code re-enables the effect, and conditionally restored on toggle OFF or switching out of ID6. All operations are guarded by runtime UObject checks, reflected parameter ABI checks and scalar readback. If another system already changed the parameter on exit, the bridge does not overwrite it.

The shared world scalar affects all game rendering, not just held weapons. The hypothesis is that removing this first-person distortion will align mesh silhouettes across fovea/periphery; **it has not been proven in headset**. Keep the original Build 182/186.1 installation available.

## Source-only validation

Updated `stage8_config_tests.cpp` verifies the single frame-latched global boolean, replacing the previous independent per-view factor tests. Windows native DLL building depends on the exact restricted Joey SDK `joeyhodge/UESDK@3cffbc82429b6165ceec2714f0f0d9ae48f55596`; previous exact-SDK CI failed checkout, while the public SDK substitute passed the DuoView standalone tests but failed the main backend due to missing proprietary SDK headers. The workflow attempts both, and **must not publish a DLL as functional if the build fails**.

## Headset verification

1. Run from a separate test installation; do not replace stable Build 182/186.1.
2. Select ID6, set eye gaze to fixed-center and feather to 0. Compare weapon/detector/knife/hand outlines between diagnostic source 1 (periphery) and 2 (fovea), at the same position.
3. Enable global first-person FOV bypass. Confirm status 6 and nonzero verified counter. Check weapon seams for hip-fire, ADS, reloading and gaze movement.
4. Disable the option, verify restoration of the original scalar (unless overwritten by the game), change to ID5 and check normal rendering.
5. Exercise level loads and exiting ID6. If any FOV effect remains globally disabled, restart the game and do not re-use the experimental DLL.

## Fallback

An optional Lua overlay implements the same global scalar write on the already compiled stable v186.1 UEVR binary. It is a separate experiment, **not** a newly compiled native backend. It uses the existing LuaLoader from Joey UEVR and activates only while ID6 is selected.
