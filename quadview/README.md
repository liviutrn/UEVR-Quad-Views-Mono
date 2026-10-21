# Stereo Quad Views — Build 47 diagnostics follow-up

Build 47 carries the Build 46 renderer plus an on-demand, read-only
diagnostics export for QuadView delivery and target retirement. It also skips
the existing queue-device query when there are no staged native owners. This
is a diagnostic and bounded CPU-work increment; it does not add an adaptive
resolution controller or claim a frame-rate gain. See
[`RELEASE_NOTES.md`](RELEASE_NOTES.md) and [`VALIDATION.md`](VALIDATION.md).

Build 47 targets STALKER 2 (UE5.5), DX12, OpenXR and PSVR2. ID7 renders four
independent engine-owned sources: left/right context and left/right focus. The
compositor keeps separate images for the two eyes; runtime quad-view support is
not required.

Build 47 includes Build 46, which starts from the accepted Build 40 source
`7486fc59890b14673cd50770b0dafeb692576716`. It retains Build 40's FOV, gaze,
crop and stereo behavior and keeps ID6 DuoView separate. See
[`READ_FIRST.txt`](READ_FIRST.txt) for install and in-game comparison steps.

Each draw freezes its target set, stereo pose, projections, gaze and settings.
Build 46 selects the unique main view family by its frozen family, scene,
target and four view identities. The first native callback keeps the original
family batch, including auxiliary families; the remaining callbacks receive
only the selected main family as a singleton.

The four rendered outputs can share deferred Slate command tails. A shared
tail completes only the native view slots actually attached under the same
identified worker drain and command list. If ownership is ambiguous or more
than one quartet shares a tail, every covered engine owner still drains, but
the affected source packets cannot be published. Attachment order is not used
as a guess about physical GPU write order. Distinct tails continue to work.

Per-target content stamps track the packet that last wrote each physical
output. A late older write invalidates any packet that no longer matches all
four target contents. A future queued quartet is not poisoned before it writes,
so normal frame overlap can recover when that quartet completes coherently.
Queued RHI owner records also retain their source packets through the original
CPU command callback, including across a ledger reset.

Build 40's crop geometry, gaze controls, fixed-center option and focus-only
Glamarye sharpening remain in use. Default focus is 50% × 50%; context
resolution is 20% per axis; sharpening defaults to 1.0, with zero bypass.
Source targets retain full atlas extents to preserve engine view rectangles
and projections, increasing render-target memory use.

The automated tests exercise shared-tail attachment, deferred-owner lifetime,
late writes, content-stamp agreement across 40,320 write orders, fresh-frame
recovery, target-set replacement, auxiliary-family routing and restoration of
the original family batch. Windows CI builds the production DLL and runs the
Windows-only shader and compatibility suites. Neither CI nor synthetic shader
colors establish actual headset lighting parity or stability.

Display-gamma parity, in-game shading and shadow behavior, live GPU-fence
retirement, and performance have not been measured on a headset. The nominal
rectangles cover 29% of ordinary native-stereo raster area at default settings;
this pixel-count calculation does not predict GPU time.

To export the new diagnostics, open **Debug → Stereo Hook Options → Hook
Provenance Diagnostics**, then use **Refresh Hook Provenance** and
**Export Hook Provenance JSON**. The checkbox is default-off. Its QuadView
delivery, RHI-record and retirement sections are independently sampled; busy
components omit their counts, and bounded retirement counts carry a truncation
flag. These observations do not prove GPU completion or queue ordering.

Diagnostics: 0 blended, 1 context only, 2 focus only, 3 synthetic source
colors. Synthetic colors prove compositor mapping only. Keep the Build 40
installation for direct comparison and retain the complete log after a failure.

Based on Joey/praydog UEVR and the project's accepted DuoView/QuadView work.
The fused sharpening derives from Robert Jessop's Glamarye Fast Effects for
ReShade; see `GLAMARYE_LICENSE.txt`.
