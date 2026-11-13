# UEVR World Trace #21 — passive telemetry (experimental)

This trace builds on the existing TriView B43 + DuoView M2.3 source and makes **no rendering/pose modifications**. It is off unless `UEVR_WORLD_TRACE21=1` is in the same `%LOCALAPPDATA%\\VectorXR\\framegen-research.txt` preset used for VectorXR #21.

## What is recorded
Rows are `kind,frame,secondary,tick,qpc_ns,display_xr,pose_xr,aux`. The `tick` column is the monotonic game-tick sequence (the `kGameTick.frame` field is not an accurate game frame ID). Join `kGameTick.tick` to `kRender.tick`, then `kRender.frame` to `kPose.frame` and `kSubmit.frame`. Take the last `kPose` for the frame before submitting. Join `kSubmit.display_xr` to the VectorXR `kXrRealEnd.display_xr` value and corroborate by QPC. Reject duplicated, stale, missing or ambiguous joins.

The sampling ring keeps the most recent 131,072 records, allocated only when enabled, with atomic per-field updates and periodic asynchronous file snapshots every 20 seconds. Data survives startup and loading. Each launch writes a distinct filename `uevr-world-trace21-YYYYMMDD-HHMMSS-ffffff-MODE.csv`. The VectorXR trace uses the same timestamped scheme. A/B/C/D logs therefore cannot overwrite each other, and users should not have to manually copy them between runs.

`qpc_ns` is `std::chrono::steady_clock` nanoseconds since the runtime's monotonic epoch, intended for same-process timing correlation. Validate its mapping against OpenXR time before calculating world-stamp errors. P95 interval drift >=3ms at 120Hz supports further investigation; <=1ms argues against it, provided the frame join is reliable.

Trace stops on DLL/process termination; 20-second snapshots reduce loss on abnormal exits. This isn't a proof that the rendered-world state is exactly the game tick: UE5 pipelining may still introduce lag. Check tick-to-render ordering and actual submission identity in logs.
