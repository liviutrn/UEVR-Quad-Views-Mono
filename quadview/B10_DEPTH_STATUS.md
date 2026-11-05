# B10 engineering checkpoint — not an all-fixed build

Implemented exact finite-depth camera reprojection, frozen physical eye origins, captured jitter metadata, exact source identity lookup, producer fence retirement and command-list recording epochs. Source owner scopes deliberately reject mixed roles. 22 portable tests pass, including independent near/far/asymmetric/canted geometry and ownership/fence tests. New overlays replay against generated pinned backend; Windows validation pending.

Capture remains disabled. The retained final RHI callback does not prove that NGX evaluates inside that callback; preceding and parallel RDG evaluations cannot inherit its identity. Enabling this on an assumption can either capture no depth or attribute the wrong view. A finer pass/list association or observed exact callback coverage is required. Also current completed-only depth lookup needs a consumer queue fence wait for reliable same-frame composition. These are functional blockers, not debug UI issues. This checkpoint must not be advertised as repairing synthesized stereo or all seams.

B9 run20 compiled shaders but failed the three WARP variants because the new test requested portable sharpening7 outside its allowed0..2 contract. B10 uses2; production sharpening settings are unchanged.
