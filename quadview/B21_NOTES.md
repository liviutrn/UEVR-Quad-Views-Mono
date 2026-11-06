# TriView B21 — B15 stable depth selection on B18 protected rendering

Parent: B18-42 (last confirmed to render reliably) `1a96e7b1cc7f71304ed106ec00424f5f14a6bf15`.
Reference: B15-27 `55b99d075dd6c2307dcb1833f3969c9f9e55566c`.
B15-27 user test: no perceptible depth-to-mono flicker; rare short black-right-eye flicker.
B18-42 user test: stable physical-eye rendering but frequent periphery depth loss.

## Single intentional behavior change
Restore the **B15-27 latest submitted periphery depth within 250 ms**
rather than requiring its NGX recording timestamp >= the color source packet
birth timestamp. NGX, RT/RHI and present stages can overlap, making the
B18 packet-born cutoff drop usable depth. This is a specific regression
hypothesis, not proof of exact per-frame matching.

B21 changes the depth selector, its D3D12 consumer invocation, and an ImGui
tooltip. B18-42 stays unchanged. **No B19 GPU Wait**. No new GPU
work, new textures, allocation-count changes, extra CPU copying, or shader
changes.

## B18 improvements retained
Three native physical color targets, no dormant right-periphery allocation,
true stereo foveas, shared mono periphery, native-only publication, async
resource ownership / fenced retirement, command-list Reset epochs and
Execute bookkeeping, user menu scroll, and per-role texture reuse on resize.

## Honest limitations
A depth snapshot can be from an adjacent rendering frame (as in B15-27).
No exact depth/color provenance; no promise of flicker-free output or
lossless frame matching. If GPU submission is delayed >250 ms, no snapshot
is accepted. Foreign-queue depth still requires completed fence; no new
cross-queue wait or potential stall. B15's rare right-eye blackouts are
separate, likely source/admission/presentation issues; B21 keeps B18's
later native-target safeguards instead of reverting the entire B15 binary.

## Testing
After Windows CI finishes, headset at same location/settings: start ID7
directly; verify BOTH foveas stable and right eye no black flash; inspect
gray periphery-depth diagnostic over 60+ s stationary and during head
movement; evaluate no magenta or mono shifts. Compare to B15-27 and B18-42.
Test on/off depth and one periphery resize. Log depth used/missing delta,
FPS and frame pacing. Do not merge until user verifies.
