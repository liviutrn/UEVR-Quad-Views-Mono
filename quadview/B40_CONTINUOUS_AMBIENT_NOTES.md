# B40 — Continuous Ambient Temporal (experimental)

Base: B39-133 commit `5c6a85cc009bbed46037fcfdc1cfddd2ed735a6a`. Separate mode 6 so B39 (mode 5), B37, B31 remain selectable and unchanged.

### Core
- 128 spatial sample centers per eye (4 per each of 32 display/control knots), 15 spatial RGB-difference taps per center = 1,920 pairs per eye, 3,840 for both eyes. Sub-anchor locations are deterministic.
- Trim top and bottom per-channel outliers from each valid 4-point group; three use RGB-component median; two use mean; fewer than two do not update. Invalid depth, nonfinite or filled samples do not overwrite history.
- 32 persisted RGB correction knots per eye, using the existing fenced, queue-owned history buffer. B40 alone ignores crop displacement, scene epoch, settings epoch and elapsed>250 ms reset logic. No motion-triggered or invalid-sample resets.
- One time-domain EMA with a rate bound from the same preset. Long frame gaps clamp integration elapsed to 50ms so a stalled frame cannot flash. First allocation initializes from zero and ramps up.
- Fast 75ms, Balanced 200ms, High 350ms (default), Maximum 600ms. Rate bound = 100/tau RGB/sec. This is intentional color trailing rather than jumping.
- B40 continues displaying retained correction when depth alignment becomes invalid; it simply does not accept an invalid new measurement. No new allocations or readbacks. B38 original B27 inward feather remains ON.
- Runtime/device/queue resource ownership and fence lifetime safety MUST NOT be removed. The new buffer after an actual device/session restart must be initialized. This is not a scene/motion reset.
- B40 UV correction field is low frequency, interpolated between the original 32 knots. No instantaneous per-pixel border copying.
- UI: new B40 selected by default in clean settings; correction strength, temporal preset, original B27 feather. Legacy B31/B37/B39 settings hidden for this mode. Original settings controls remain for other modes.

### Testing
B40 static numerical contracts, generated UI, settings range, B39 regression gates, FXC production shader, D3D12 WARP/other backend/frontend suites in the full Windows CI. Deterministic filter tests do not prove perceptual zero flicker; headset checks must cover still, very slow gaze/head, fast motions, low real fps, depth loss, reload, and switching modes. Inspect GPU ms: 4x B39 ambient analysis workload is not necessarily free.

**Caveats:** Invalid geometry can mean a retained correction no longer exactly matches the current scene; this is an intentional tradeoff. True zero perceptible flicker cannot be guaranteed by source tests.
