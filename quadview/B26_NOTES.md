# B26 — OpenXR session boundary fixes (2026-11-06)

**Baseline:** B25 independent-safety commit 09156513ffa6f5295f1e20bc96943ab94769d95a.
**Scope:** OpenXR reinitialize after save reload, no change to four logical roles /
three source textures, four-sample reprojection, eye layouts or normal rendering.

## Three concrete defects addressed

1. **Incomplete GPU preflight:** B25 proved only the OpenXR texture
   CommandContext fences before calling inherited `wait_for_all_copies()`.
   That helper may block on other game/UI/spectator/scene commands. B26
   requires UEVR's existing comprehensive `mono_consumers_retired()` proof
   before entering the destruction path when in TriView restart phase 3.
   An unretired command delays restart; it is NEVER freed on a timeout.

2. **Stale native stereo readiness:** the Native Stereo Fix hook persists across
   XR session reinit, and `PairReady` may describe a previous session. B26
   captures the monotonic native packet publication serial just before
   reinit and permits TriView re-entry only when the newly created runtime
   reports fresh tracked poses AND a strictly newer published Native Stereo
   packet, held ready for the existing 2 seconds.

3. **Stale DLSS depth after XR restart:** the B21 latest-depth policy may use
   a submitted depth buffer up to 250 ms old, which spans a rapid restart.
   B26 drops completed, unleased depth snapshots before restarting the old
   OpenXR session; it does NOT reset NGX feature handles, inline hooks,
   D3D12 device, command queue or outstanding fence state. If any copy is
   pending or leased, the restart is postponed.

## Deliberate safety tradeoffs

- All new checks occur only during the rare restart transaction.
- A hung/removed GPU or unresolved native owner cannot be safely erased.
  In that case the reset is postponed or rendering stops after an
  irreversible OpenXR teardown failure; an application restart may remain
  necessary. No finite timeout can make destroyed GPU resources safe.
- Avoid repeatedly selecting Reinitialize Runtime while a reset is pending.
- **These are verified source-level defect repairs, not proof that the user's
  kernel 0x139 / Arg1=3 is eliminated.** That needs WinDbg symbolized driver
  fault attribution and cautious headset validation. The crop-size failure
  had no logged target reallocation immediately preceding it, so do not
  blame VRAM or announce a proven crop BSOD fix.

## Test sequence (only after passing Windows + sanitizer CI)

First test existing stable build and baseline configuration; then try B26
with Dynamic FG disabled, start in TriView and use one manual runtime reload.
Check automatic return from Native Stereo, depth reactivation, original UI
positions, hands and GPU frame time. Only after success test actual save
reload + Dynamic FG. Avoid deliberately reproducing a kernel crash through
rapid repeated size slider changes.
