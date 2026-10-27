Joey stock DIBR test package
============================

This patch builds on the pinned Joey UEVR backend commit
5ac7edc207866569334175e4ed8a7517971547f6, with UESDK
3cffbc82429b6165ceec2714f0f0d9ae48f55596 and matching injector frontend
60be4b0f9a646109fd9fdf448bacd41477234091.

The patch uses Joey's existing Synthetic DIBR rendering method IDs only:

  3  Synthetic Stereo (DIBR, Experimental)
  4  Synthetic Stereo (DIBR Single View, Experimental)

It adds no rendering-method IDs and contains no DuoView implementation.

Test setup
----------

1. Extract this package into a new, separate test folder. Keep any known-good
   UEVR installation untouched.
2. Launch STALKER 2 in DX12 with the OpenXR runtime selected in the injector.
3. In UEVR, turn Native Stereo Fix off and select method 3 first. The saved
   Use Same Stereo Pass preference stays unchanged and is inactive while Native
   Stereo Fix is off. Enable “Enable DSV/RDG Depth Capture (Experimental)” in
   the DIBR section.
4. Start with DLAA in the game. After the DIBR depth capture and output look
   stable, repeat the test with DLSS enabled and note any change in the
   reported depth dimensions or behavior.
5. To check the single-view path, select method 4. The UEVR menu must show
   “Single-view status: active”, and “Suppressed engine-view frames” must keep
   increasing while the game renders. Both readings are needed to confirm
   that the one-view path is running.

For a first R6 comparison, keep True Reprojection Strength at its existing
default of 1.0. The optional “Max stereo strength (2.0)” button is an explicit
change and should only be used when exaggerated stereo is wanted. Switching
between Native Stereo, Sequential (Alternating), and DIBR uses the normal full
mode transition and warmup; it is not a same-frame A/B comparison. DIBR requires
Native Stereo Fix to be off, and the comparison controls leave that preference,
convergence, DIBR calibration, and strength unchanged.

R6 depth inspector and calibration
----------------------------------
The STALKER 2 DX12/OpenXR DIBR panel includes normal stereo, raw depth, readable
depth, depth edges, depth-over-color, and reprojection-confidence views. Raw
and readable depth are shown equally to both eyes. Confidence describes the
inverse reprojection solve and is not a visibility buffer or hole mask.

Depth Sampling defaults to R5 linear. Point and edge-aware sampling are
available as opt-in alternatives. Edge-aware sampling falls back to point
sampling at a depth discontinuity. Isolated-spike repair is off by default. Its optional median
repair only changes an isolated outlier when the surrounding samples are
coherent; the threshold uses raw device-Z and does not represent metres. The
Depth Scale default of 1.0 leaves captured device depth unchanged. Display
exposure changes visualization only. These controls do not provide a metric
depth calibration.

Preserve Stereo Strength is enabled by default in the STALKER 2 scope. It
bypasses saved edge stabilization, UI edge/footprint blends, and legacy color
repair that can reduce local disparity; it keeps the existing reprojection
strength value. The saved legacy controls are retained for other scopes.
“Reset depth calibration” restores depth sampling, repair, threshold, exposure,
scale, and inspector view while retaining reprojection strength, selected depth
candidate, and comparison mode.

Depth candidates are bounded IDs for resources that passed the capture and
producer-proof checks. IDs and their size/format metadata do not identify a
semantic camera. Availability is a current-frame status; selecting a known ID
waits for a fresh verified slot and does not fall back to an unrelated source.
The registry can replace its least-recently-seen older nonselected entry; if
all entries are current or manually selected, a new identity is rejected
instead of evicting one. A manual selection fails closed while its candidate
is unavailable. A capture reset invalidates its IDs and returns selection to
automatic mode; IDs are not reused. Shape, queue, and viewport proof still
cannot establish camera identity, so an in-game review of the selected source
remains necessary.

The CI workflow runs the depth-policy checks, Windows WARP checks, the full
original Joey compatibility suite, and builds the injector package. These
checks do not verify STALKER 2 runtime behavior or headset stability. This package has
not been verified in-game unless separate runtime testing is recorded.

Revision 2: first headset-test corrections
------------------------------------------
The first test produced no depth and showed a misaligned duplicated-eye
fallback. Revision 2 preserves original two-view stereo during warmup,
hooks binding/viewport/reset methods on all queried D3D12 command-list
interfaces, and samples the observed valid viewport inside reused or padded
depth allocations. Its log reports exact rejection categories and binding
hook counts. DIBR tuning sliders affect the image only after synthesis is ready.
No game input code was changed.

The actual format-19 depth/stencil resource is now accepted and sampled using
its format-21 depth-plane SRV. Earlier documentation misidentified format 19
as plain R32_TYPELESS (which is format 39); that caused valid depth to be rejected.
The GPU test now uses padded R32G8X24_TYPELESS / D32_FLOAT_S8X24_UINT resources,
including full depth-plane copy and live frame updates, under the debug layer.

Revision 3: actual presentation queue submission
-----------------------------------------------
R2's game log recorded 35,772 depth copies from 3616x1436 format-19 resources,
but zero submitted/consumed captures. Its submission hook covered only the
temporary setup queue's vtable. R3 also hooks each actual presentation queue
discovered from the live swapchain and uses the correct original function for
each distinct slot. It accepts COM interface aliases of the same queue,
uses NVIDIA's documented Streamline native-interface QueryInterface GUID
to hook underlying native queues as well as their wrappers,
observes both outer and native inner queue forwarding layers,
matches command-list aliases by COM identity, and supports another direct
scene queue through a producer fence and a presentation-queue GPU wait.
It still requires binding/viewport proof from that same producer queue.
New exec[all/same/matched/alternate/resetDiscard] counters distinguish missing
submission callbacks from queue mismatch and discarded recordings.

The Windows GPU regression now uses the production queue-hook helper to
deliver actual ExecuteCommandLists callbacks. It creates a distinct live
queue vtable to reproduce the setup-only coverage gap before installing the
live hook. It also verifies COM command-list aliases, a deliberately delayed
alternate producer with GPU fence handoff, rejection of proof from the wrong
producer, rejection of a later bind on the same list, safe forwarding after
hook teardown, native lists hidden by opaque outer wrappers, exactly-once
publication, reset after submission, and a real pixel change at stereo strength
1 versus 0. Resource-barrier and viewport observation are still manually
delivered by this standalone fixture; STALKER 2 itself remains the required
end-to-end headset test.

Revision 4: independent review corrections
------------------------------------------
Publication now selects the exact most recent DSV/viewport binding executed
before the depth copy on its actual producer queue. A larger binding on an
unsubmitted list cannot change the sampled rectangle; A -> B -> A bindings
retain the final A. The Windows GPU test reproduces both cases.

Reprojection strength now scales the mapping being solved. Previously, the
second solver iteration could undo stereo at strength 2. The production
shader is checked at strengths 0, 0.5, 1, 1.5, and 2 against exact plane
displacement, with matching strength in the spatial-repair residual.

Single-view construction is restricted to the main game viewport Draw, after
three stable validated main-family observations and three consecutive ready
DIBR outputs from the same resource generation. Unrelated scene captures
retain their normal view count. A failed output resets consecutive warmup.

Revision 5: adversarial failure and lifecycle corrections
--------------------------------------------------------
Allocation and descriptor preparation now finish before GPU recording starts.
An abandoned recording is closed and discarded before its input resources
can retire. Output state is committed only after a checked submission; a
failed Close, Signal, or event-arm operation cannot activate single-view
suppression using an output that was never submitted. The three-slot ring
falls back to ordinary stereo when no safely reusable slot is available.

Submitted resources with an unprovable retirement fence are quarantined.
Recording-list Reset cannot release already submitted depth after a failed
producer or consumer Signal. Pending depth generations continue receiving
late Execute/Reset retirement callbacks after the capture mode is disabled.
Observer detach drains callbacks before releasing the observer's owner.

Cached DSV replay and live descriptor replacement are serialized. Queue
callbacks preserve actual same-queue enqueue order, while independent queues
remain concurrent. Changing UWorld invalidates single-view readiness before
new views are constructed. UI alpha is supplied when any footprint/edge/mask
consumer needs it, independent of the edge-guard switch.

Depth capture is opt-in again. Enable "Enable DSV/RDG Depth Capture
(Experimental)" explicitly for this STALKER 2 test. Keep VectorXR disabled
for this test, as in the clean injection setup.

Remaining test boundary: shape, ordered DSV binding and queue provenance do
not establish semantic camera identity. A secondary camera with the same
viewport dimensions can still qualify. candidateSources in the depth summary
reports distinct eligible depth sources, but is not a camera discriminator.
The Windows tests cover production shader/capture/hooks and shared transaction
helpers; they do not execute STALKER 2, a headset, or the entire production
component's failure paths. An in-game test is still needed to establish that
this exact package works on the target runtime.

The slot retirement marker now follows all spectator and runtime consumers,
including early frame exits. Resize and mode exit retain presentation textures
and descriptor heaps until those consumers retire. Optional UI snapshots have
an independent checked producer submission and lifetime; a failed DIBR frame
cannot release a UI snapshot whose copy is still in flight.

Revision 6: inspector and candidate tools
-----------------------------------------
The R6 workflow applies the inspector/calibration shader stage after all eight
R5 stages, then applies the comparison and inspector UI stage before tests and
builds. The shader stage also copies the portable candidate policy header into
the generated backend. Portable candidate-policy tests run on Linux and
Windows; Windows WARP, the pinned backend build, the full compatibility suite,
and headset validation must be read from the matching workflow run. No R6
acceptance result was recorded; the user's negative headset feedback is
summarized under Revision 7.

Revision 7: visibility reconstruction and producer-pattern IDs
--------------------------------------------------------------
R6 headset feedback was negative and does not constitute acceptance. Automatic
depth selection produced an image, but the displayed physical candidate ID
changed more than once per second and manually selected IDs did not work
reliably. R6 IDs identify individual D3D resource objects. When the engine
rotates resources for one logical stream, an exact physical ID can have no
fresh slot in a Present interval even while another allocation is active. R6
failed closed instead of using an unrelated or stale depth image.

R7 now records physical members separately from heuristic producer-pattern IDs.
A new allocation joins an existing pattern only when its executed route is
compatible and is corroborated by a repeated DSV descriptor handle or the
exact same nonzero D3D resource debug-name hash. Format, viewport, queue, route
shape, and ordinal alone cannot merge resources. These markers can be shared
by unrelated passes or recycled; they are heuristics, not unique camera proof.
If evidence is missing or contradictory, the candidate stays separate or is
marked ambiguous; an ambiguous pattern cannot be manually pinned. Resource
names may be absent and DSV handles may not stay stable across a pool, so a
rotating source may remain split into physical candidates and manual selection
may still be unavailable. The grouping does not establish semantic camera
identity or prove that depth and color came from the same camera. Windows WARP
and headset verification are pending.

Auto initially uses the R6 largest-area/latest-sequence winner, then holds its
current choice indefinitely while it remains fresh and valid. Resource size
alone never upgrades the choice. Auto changes after the current choice is
absent or invalid for three consecutive epochs. During that grace period, it
may acquire a fresh current-frame physical fallback; it never uses a
previous-frame slot. Manual pattern selection stays pinned and fails closed if
no fresh matching physical member is available.

R7 adds a selectable Visibility-aware reconstruction mode (the new UI default)
and retains R6 inverse reconstruction for comparison. The R7 path
forward-projects current source pixels and builds per-eye unsigned-integer
visibility-depth and source-index maps. A depth pass picks the nearest
projected surface; a source pass chooses a deterministic winner for equal-depth
collisions. The resulting source-index map marks actual coverage and holes for
the current frame. It uses no temporal color or depth history.

Background fill defaults to a 32-pixel search radius, is bounded to 64 pixels,
and can be disabled with radius zero. It fills only a small hole with visible
samples on both sides, a depth discontinuity at its boundaries, and a stable
farther background run. It cannot reveal surfaces hidden from the captured
view, recover missing geometry, or establish camera provenance. The coverage
inspector uses green for covered pixels, cyan for bounded fill, red for
unresolved regions using the R6 geometric fallback, and purple when visibility
is unavailable. Inspector views 1–5 and reconstruction mode 0 retain the R6
views/path. If visibility support, pipeline creation, or scratch allocation
fails, the optional path reports the reason and the current frame uses R6; it
does not block normal R6 setup. Near-character artifacts from incorrect or
incomplete input depth remain unresolved by this pass.

The user found that strength 2.0 looked like reduced world scale and prefers
1.0. Strength 1.0 remains the preferred baseline; increasing strength changes
perceived scale and is not a quality setting. Near-character artifacts also
remained in R6, and its isolated-spike repair did not improve them.

The workflow applies R7 visibility shader, visibility pipeline, and stable
depth-selection UI after both R6 stages. The R6 shader stage still copies the
capture headers into the generated backend before R7 runs. Source pins and the
existing policy/WARP test step, backend build, compatibility targets, frontend
tests/build, and package order are unchanged. `run_tests.py` marks the new
Windows-only R7 visibility analytic oracles, stable named-depth rotation, and
legacy null-visibility-UAV fallback as Windows-only in its `test-scope.json`
output. The local portable policy tests reported zero failures, including a
150-epoch check that a larger resource does not replace a fresh Auto choice.
Windows WARP, full builds, compatibility tests, and headset behavior remain
pending. No R7 headset acceptance is claimed.
