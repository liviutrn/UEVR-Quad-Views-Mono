# TriView B20 — SAFE B18-42-derived performance experiment
Parent (last headset-starting B18-42): `1a96e7b1cc7f71304ed106ec00424f5f14a6bf15`.
B19-49 not included: NO compositor queue Wait, no new GPU synchronization.

## Exact changes
- `set_enabled` no longer mutex-locks and scans the 12-slot depth pool on every
  present. It prunes immediately on mode/size transition and retries safe
  fence-based resource retirement every 32 present calls.
- The selector and the NGX capture read width/height atomically as one 64-bit
  extent, avoiding mixed dimensions during resizing.
- Preserve B18-42's startup, rendering, three physical color sources, depth
  selection, foreign-queue completion checks, resource ownership and shader.

## What this does NOT do
This does not guarantee continuous periphery depth. B18's foreign-queue
completed-fence gate remains, and depth-to-color identity remains approximate.
It is a CPU path optimization, NOT a fix for reprojection flicker.
There are no new GPU waits and no GPU stalls added by this patch.

## Verification
Only test after CI is green. Use B18-42 as immediate rollback if start fails.
At identical settings compare CPU-limited FPS, 1% lows / frametimes, GPU and
VRAM. Toggle TriView, depth, change periphery resolution, reload map and check
depth valid/missing counters. No main branch merge until headset validation.
