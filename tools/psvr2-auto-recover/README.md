# PSVR2 AutoRecover v0.1 (experimental)

A very small **non-VR-overlay** Windows 10/11 utility for PSVR2 + SteamVR + BnuuySolutions/PSVR2Toolkit's modified Sony driver. It uses the official OpenVR background-client API to observe HMD tracking and, on sustained 3DoF fallback, sends the existing UnitySetup `Refine Map` and (if needed) `Activate Map` commands to the Sony driver. **It never clears the SLAM map, never redraws your play area, never changes DLLs, and never restarts SteamVR or UEVR.**

## Prerequisites

- PSVR2Toolkit modified driver installed as usual, and SteamVR running.
- Windows x64.
- `PSVR2AutoRecover.exe` and `openvr_api.dll` in the same folder (both provided by the Windows CI build).
- **Don't run multiple copies.** Quit older copies first. While UnitySetup is actively doing room setup, close AutoRecover to avoid overlapping driver commands.

## Use

1. Extract the Windows Actions artifact zip to any permanent folder. Do **not** copy anything into the PSVR2 driver folder.
2. Double-click **Start-Diagnostic.cmd** for the first test; move the headset around with normal 6DoF, then reproduce the 3DoF failure. Read `%LOCALAPPDATA%\PSVR2AutoRecover\recovery.log`. This confirms whether SteamVR reports `tracking=300` (rotation-only) or another state. Diagnostic mode sends **no commands**.
3. Close that diagnostic console process (in Task Manager if minimized). Double-click **Start-Auto.cmd** to enable automatic recovery. It stays minimized and logs transitions. One startup copy is enough.
4. Optional: double-click **Refine-Now.cmd** to request a **single non-destructive** map refinement manually (while SteamVR is running).
5. To start automatically when Windows logs in, create a shortcut to `Start-Auto.cmd` in the folder opened by `Win+R` -> `shell:startup`.

If there are multiple copies of the tool running, stop them before testing.

## What automatic recovery does

- Polls OpenVR head pose every 500 ms. A `Fallback_RotationOnly` tracking result = 300 is considered 3DoF. Also notices sustained calibration/out-of-range errors. An unplugged headset never triggers recovery.
- On sustained loss (>4 sec for 300 after previous 6DoF; >10 sec on startup; >15 sec for other degraded states), signals `Refine Map` = `0x2` via the same named Win32 shared memory, mutex and event as UnitySetup.
- During recovery sends the same temporary play-area camera keepalive used by UnitySetup (once per second).
- If still bad after 12 sec, signals `Activate Map` = `0x4` once. Checks whether SteamVR reports healthy tracking for 3 sec. If not recovered, stops commands for 120 sec.
- Does not send `ClearMap` = `0x20` automatically or on the command line.

## Important limitations and safety

**Prototype, not yet tested with a real PSVR2 headset.** OpenVR might report `Running_OK` even when the user observes 3DoF with some Sony driver builds. The program logs Sony's separate tracking status too, but does *not* assume what its undocumented integer values mean. A `Running_OK` reading is not a guarantee of actual positional tracking. Validate in diagnostic mode first. The driver may also ignore refinement without its room-setup UI active. Do not assume that signalling a command means SLAM successfully reacquired. 6DoF requires adequate lighting/trackable scenery and working cameras.

The `Refine Map` and `Activate Map` commands are observed in the public [UnitySetup source](https://github.com/BnuuySolutions/PSVR2Toolkit.UnitySetup/blob/main/Assets/Scripts/PSVR2SharedMemory.cs). This implementation targets the same memory protocol and may not apply to every Sony driver/Toolkit version. The 32MB shared-memory view is **system RAM**, not a new VR render target. No SteamVR overlay is created.

For a real test, provide the log from good 6DoF, a 3DoF episode, and after recovery. If the Sony status changes while the OpenVR result remains 200, detection must be adapted using observations, rather than guessing the status integer codes.

## Building

Windows runner with MSVC:

```
git clone --depth 1 https://github.com/ValveSoftware/openvr.git openvr
cl /nologo /std:c++17 /EHsc /W4 /O2 /I openvr/headers src/main.cpp /link /OUT:PSVR2AutoRecover.exe openvr/lib/win64/openvr_api.lib
copy openvr\bin\win64\openvr_api.dll .
```

The workflow at `.github/workflows/psvr2-autorecover-windows.yml` builds, runs offline smoke tests, and uploads the portable Windows artifact.