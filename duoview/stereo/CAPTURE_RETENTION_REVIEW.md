# Current-interval depth retention correction

The capture allocator previously selected the first GPU-retired slot. A
producer fence can finish before Present consumes that slot. A later pass in
the same epoch could then overwrite an earlier foveal copy, despite having
ample unused slots and no per-interval quota skips. This invalidates the
assumption that the eligible inventory contains every submitted write version.

The correction reserves occupied current-epoch DuoView slots until
`finish_frame`. It preserves all existing pending/leased/quarantined and GPU
retirement checks, never admits old-epoch depth as current, and keeps the stock
single-depth allocator behavior. The bounded 12/48-copy quotas remain.

The Windows workflow first compiles the actual old generated capture header
against `capture_retention_warp.cpp` and requires the loss to reproduce. It
then applies the correction and runs the identical two separately submitted
and completed passes, requiring both copies to remain selectable. Both normal
and snapshot budgets are exercised. Existing capture and full rendering suites
still run afterward.

The earlier fixture recorded all passes before executing any of them. Its
passing result could not exercise this schedule. CPU slot-policy tests cover
the independent producer/consumer lifetime rule; they do not replace WARP.

CI31 also introduced mode 3 but left an older GPU fixture expecting mode 3 to
be rejected. The invalid-mode test now uses 99, and mode 3 gains an executable
peripheral-equality check. This fixes that stale test without dropping invalid
mode rejection.

This is a concrete capture-lifetime repair, not certification of actual
Unreal depth eye/frame/stage identity or a complete reconstruction algorithm.
The geometry replacement is a separate next change. V3 and stable branches
are not changed.
