# Experimental M41 provenance diagnostic — no playable quality release

This branch adds an opt-in M4.1 metadata-only instrumentation post-pass after
the normal M4.1 generated source overlay. It does not change depth selection,
resource copies, shaders, runtime defaults, or the current production algorithm.

The added counters describe accepted/rejected NGX capture intervals, lookup
readiness and Present epoch offsets; epochs do NOT prove causal scene identity.

CI must compile the full Windows backend and frontend, execute existing
regression tests, and upload evidence. Even a successful CI build does not
validate headset quality or RTX timing. No merge into playable branches.
See research/duoview-improved-stereo/PHASE_B_20261116_M41_PROBE_AND_CANDIDATES.md
