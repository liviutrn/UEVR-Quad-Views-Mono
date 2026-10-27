#!/usr/bin/env python3
"""Supply a dedicated foreground MPC reset epoch after Build49 OpenXR patch.

Mono rendering-method selection generation is not the same as OpenXR runtime
reinitialization. This narrow VR.hpp edit explicitly signals the latter.
"""
import sys
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_foreground_runtime_epoch.py <backend>")
backend = Path(sys.argv[1])
file = backend / "src/mods/VR.hpp"
s = file.read_text(encoding="utf-8-sig")

def one(old, new):
    global s
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f"Unexpected Build49 baseline anchor count {count}: {old[:90]!r}")
    s = s.replace(old, new, 1)

one(
    '    const ModSlider::Ptr m_world_scale{ ModSlider::create(generate_name("WorldScale"), 0.01f, 10.0f, 1.0f) };',
    '''    const ModSlider::Ptr m_world_scale{ ModSlider::create(generate_name("WorldScale"), 0.01f, 10.0f, 1.0f) };
    // Incremented exactly when OpenXR Reset Runtime replaces the runtime.
    std::atomic<uint64_t> m_foreground_mpc_runtime_epoch{0};'''
)
one(
    '''    auto get_world_scale() const {
        return m_world_scale->value();
    }''',
    '''    uint64_t foreground_mpc_runtime_epoch() const {
        return m_foreground_mpc_runtime_epoch.load(std::memory_order_acquire);
    }

    auto get_world_scale() const {
        return m_world_scale->value();
    }'''
)
one(
    '''        m_openxr.reset();
        m_runtime.reset();
        m_runtime = std::make_shared<VRRuntime>();

        m_controllers.clear();''',
    '''        // Keep active foreground MPC state aware of runtime reinitialization.
        // No GPU changes, no changes to Mono optical alignment persistence.
        m_foreground_mpc_runtime_epoch.fetch_add(1, std::memory_order_acq_rel);
        m_openxr.reset();
        m_runtime.reset();
        m_runtime = std::make_shared<VRRuntime>();

        m_controllers.clear();'''
)

# An explicit Reset Runtime destroys the old OpenXR/swapchain state.
# Clear any previous ID6 quarantine only AFTER successful reinitialization.
# The first valid producer pair still gates presentation as before.
one(
    '        auto e = initialize_openxr();\n\n        // Restore BOTH the value',
    '        auto e = initialize_openxr();\n\n'
    '        if (!e && is_using_duoview_mono()) {\n'
    '            m_duoview_quarantined.store(false, std::memory_order_release);\n'
    '            spdlog::info("[DuoView][SaveReloadV2] Reset Runtime: ID6 quarantine cleared; preferences retained");\n'
    '        }\n\n'
    '        // Restore BOTH the value'
)

file.write_text(s, encoding="utf-8", newline="")
print("Applied dedicated OpenXR foreground MPC epoch to VR.hpp.")
