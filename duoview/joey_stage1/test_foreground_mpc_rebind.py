#!/usr/bin/env python3
"""Source-level regressions for DuoView MPC savegame/reinit recovery.

The production Windows build still compiles the extracted C++ in the pinned
Joey backend. These checks prevent accidentally removing lifecycle recovery.
They are not a substitute for a headset save/load/Reset Runtime test.
"""
import sys
from pathlib import Path

backend = Path(sys.argv[1])
s = (backend / "src/mods/VR.cpp").read_text(encoding="utf-8-sig")
start = "    // STALKER 2 DuoView foreground parity."
end = "    // Some Supermassive camera paths rewrite crop/aspect state during engine"
assert s.count(start) == 1 and s.count(end) == 1
block = s[s.index(start):s.index(end)]
assert s.index("void VR::on_post_engine_tick(") < s.index(start) < s.index(end)

required = (
    'const bool requested = is_duoview_renderer_active();',
    'const auto current_generation = mono_generation();',
    'fg.mono_generation != current_generation',
    'fg.runtime_epoch != current_runtime_epoch',
    'const auto current_runtime_epoch = foreground_mpc_runtime_epoch();',
    'invalidate_bindings("rendering generation or OpenXR reset epoch changed")',
    'invalidate_bindings("MPC_FOV UObject identity changed")',
    'invalidate_bindings("MPC read failed;',
    'invalidate_bindings("MPC setter failed;',
    'invalidate_bindings("MPC write did not survive readback")',
    'fg.force_reassert = true;',
    'tick_now - fg.last_tick > std::chrono::seconds(1)',
    'gameplay->get_player_controller(world, 0)',
    'controller->get_acknowledged_pawn()',
    'sdk::observe_uobject(static_cast<sdk::UObjectBase*>(pawn))',
    'invalidate_bindings("player pawn lifecycle changed during save reload")',
    'fg.pawn_identity = observed_pawn',
    'long game-tick pause; ',
    'const bool write_enabled = fg.force_reassert ||',
    'const bool write_depth = fg.force_reassert ||',
    'fg.force_reassert = false;',
    'sdk::is_current_object(*fg.getter_identity)',
    'sdk::is_current_object(*fg.setter_identity)',
    'std::abs(confirmed_enabled - wanted_enabled) > epsilon',
    'std::abs(confirmed_depth - wanted_depth) > epsilon',
    'fg.original_enabled = current_enabled;',
    'fg.original_depth = current_depth;',
    'if (!requested) {',
    '[DuoView][Foreground] MPC_FOV rebound successfully',
)
for token in required:
    assert token in block, f"Missing source contract: {token}"

# Preserve the proven release's exact two-parameter FOV math.
assert 'const float wanted_enabled = requested ? 0.0f : fg.original_enabled;' in block
assert 'const float wanted_depth = requested ? 1.0f : fg.original_depth;' in block
assert block.count('fg = {};') == 3, 'Unexpected loss of preserved original state'
assert 'fg = {};\n            }\n            if (!requested && !fg.active) return;\n            if (!fg.collection)' not in block

# The fast path must not invoke setters each frame, and verify only after writes.
assert block.index('const bool write_enabled') < block.index('const bool attempted_write')
assert block.index('const bool attempted_write') < block.index('if (attempted_write)')
assert block.index('if (attempted_write)') < block.index('fg.force_reassert = false;')
assert block.index('if (fg.needs_recovery_log)') < block.index('if (!requested) {\n                fg = {};')
assert 'if (!get_runtime()->loaded || !is_hmd_active()) {' in s
h = (backend / "src/mods/VR.hpp").read_text(encoding="utf-8-sig")
assert h.count('m_foreground_mpc_runtime_epoch{0}') == 1
assert h.count('m_foreground_mpc_runtime_epoch.fetch_add(1, std::memory_order_acq_rel)') == 1
assert h.count('uint64_t foreground_mpc_runtime_epoch() const') == 1
assert 'Restored Mono Eye Alignment after runtime reset' in h

print("PASS: exact Build45 FOV targets, world/generation invalidation, one-time forced reassert,")
print("      readback recovery, live reflection identities and conditional fast path.")
