# DuoView manual-depth DIBR test branch

This branch develops an experimental manual-depth stereo path on top of the accepted v186.1 Build49 source. The stable renderer remains the default path. Manual depth selection must never bypass producer-frame, GPU-ordering, resource-lifetime or output-layout checks.

The first delivery is a Windows test artifact, labeled `UEVR-DuoView-ManualDepthDIBR-Test-<run>`. It is packaged only after the pinned Joey backend and frontend build, existing regression suites pass, and the DIBR CPU and DX12 WARP tests pass. Those checks validate the software renderer route; they do not verify STALKER 2 depth acquisition, live RGB-depth pairing, PSVR2/SteamVR headset output, comfort, or performance.

See [`DIBR_BUILD_STATUS.md`](../DIBR_BUILD_STATUS.md) for current evidence.
