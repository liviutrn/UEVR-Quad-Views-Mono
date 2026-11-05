#!/usr/bin/env python3
"""Tri-view B12: start directly in TriView (ID7 saved in the profile).

Evidence (B11 headset log 2026-11-06): with ID7 saved, UEVR starts with active
method 0 and a pending request for 7 (Selection::initialize). That request did
not commit on its own (black headset); it committed 4 s after the user enabled
Native Stereo + Native Stereo Fix and then picked ID7. B12 performs exactly that
sequence automatically, once, at startup:
  1. cancel the startup request (Native Stereo stays active) and switch the
     Native Stereo Fix toggle ON, remembering the user's own value;
  2. once the Native Fix state machine reports Active for 3 s (or after 25 s),
     request ID7 through the normal menu path;
  3. after ID7 has committed, restore the user's Native Stereo Fix toggle.
Every step is logged as [TriView][Autostart]; while ID7 is requested or active
a [TriView][Transition] line every 2 s records what the mode switch waits for.
Run after apply_quadviews.py.
"""
from pathlib import Path
import sys

VR_CPP = Path("src/mods/VR.cpp")
VR_HPP = Path("src/mods/VR.hpp")
HOOK_HPP = Path("src/mods/vr/FFakeStereoRenderingHook.hpp")


def once(text, old, new, what):
    if text.count(old) != 1:
        raise RuntimeError(f"autostart anchor ({what}) count {text.count(old)}")
    return text.replace(old, new, 1)


def hook_header(text):
    return once(text,
        "class FFakeStereoRenderingHook : public ModComponent {\npublic:\n",
        "class FFakeStereoRenderingHook : public ModComponent {\npublic:\n"
        "    // Tri-view B12 autostart: Native Stereo Fix has submitted a validated frame.\n"
        "    bool is_native_stereo_fix_state_active() const {\n"
        "        return m_native_stereo_fix_state.load(std::memory_order_acquire) == NativeStereoFixState::Active;\n"
        "    }\n", "hook public")


def vr_header(text):
    return once(text,
        "    const ModToggle::Ptr m_native_stereo_fix{ ModToggle::create(generate_name(\"NativeStereoFix\"), false) };\n",
        "    const ModToggle::Ptr m_native_stereo_fix{ ModToggle::create(generate_name(\"NativeStereoFix\"), false) };\n"
        "    // Tri-view B12 autostart: 0 idle, 1 Native Fix warm-up, 2 ID7 requested, 3 done.\n"
        "    int m_triview_autostart_stage{0};\n"
        "    bool m_triview_autostart_user_fix{false};\n"
        "    std::chrono::steady_clock::time_point m_triview_autostart_since{};\n"
        "    std::chrono::steady_clock::time_point m_triview_autostart_active_since{};\n",
        "native fix member")


AUTOSTART = r'''void VR::service_mono_transition_game_thread() {
    auto& selection = m_rendering_method->selection();
    {   // Tri-view B12: automatic Native Stereo Fix warm-up before a saved ID7 start.
        using clock = std::chrono::steady_clock;
        const auto now = clock::now();
        if (m_triview_autostart_stage == 0 && selection.generation() == 0 && selection.pending() &&
            selection.requested() == RenderingMethod::QUAD_VIEWS_STEREO && selection.active() == RenderingMethod::NATIVE_STEREO) {
            m_triview_autostart_stage = 1;
            m_triview_autostart_user_fix = m_native_stereo_fix->value();
            m_triview_autostart_since = now;
            m_triview_autostart_active_since = {};
            m_native_stereo_fix->value() = true;
            selection.request(RenderingMethod::NATIVE_STEREO);
            spdlog::info("[TriView][Autostart] saved ID7: warming up Native Stereo + Native Stereo Fix first (user fix toggle was {})",
                m_triview_autostart_user_fix);
        } else if (m_triview_autostart_stage == 1) {
            const bool fix_active = m_fake_stereo_hook && m_fake_stereo_hook->is_native_stereo_fix_state_active();
            if (fix_active && m_triview_autostart_active_since == clock::time_point{}) m_triview_autostart_active_since = now;
            if (!fix_active) m_triview_autostart_active_since = {};
            const bool warm = fix_active && now - m_triview_autostart_active_since > std::chrono::seconds(3);
            const bool timeout = now - m_triview_autostart_since > std::chrono::seconds(25);
            if (selection.requested() != RenderingMethod::NATIVE_STEREO) {
                m_native_stereo_fix->value() = m_triview_autostart_user_fix;
                m_triview_autostart_stage = 3;
                spdlog::info("[TriView][Autostart] user changed the rendering method during warm-up; autostart cancelled");
            } else if (warm || timeout) {
                m_triview_autostart_stage = 2;
                selection.request(RenderingMethod::QUAD_VIEWS_STEREO);
                spdlog::info("[TriView][Autostart] requesting ID7 ({})", warm ? "Native Fix active for 3 s" : "25 s timeout");
            }
        } else if (m_triview_autostart_stage == 2 && !selection.pending()) {
            m_native_stereo_fix->value() = m_triview_autostart_user_fix;
            m_triview_autostart_stage = 3;
            spdlog::info("[TriView][Autostart] method {} committed; Native Stereo Fix toggle restored to {}",
                selection.active(), m_triview_autostart_user_fix);
        }
        static auto last_transition_log = clock::time_point{};
        if ((selection.requested() == RenderingMethod::QUAD_VIEWS_STEREO || selection.active() == RenderingMethod::QUAD_VIEWS_STEREO) &&
            selection.pending() && now - last_transition_log > std::chrono::seconds(2)) {
            last_transition_log = now;
            const char* reason = quadview_unavailable_reason();
            spdlog::info("[TriView][Transition] requested={} active={} unavailable='{}' outer_renderer={} view_ext={} autostart={}",
                selection.requested(), selection.active(), reason ? reason : "",
                m_fake_stereo_hook && m_fake_stereo_hook->quadview_outer_renderer_observed(),
                m_fake_stereo_hook && m_fake_stereo_hook->quadview_view_extensions_ready(), m_triview_autostart_stage);
        }
    }
    if (!selection.pending()) { return; }
'''


def vr_source(text):
    return once(text,
        "void VR::service_mono_transition_game_thread() {\n"
        "    auto& selection = m_rendering_method->selection();\n"
        "    if (!selection.pending()) { return; }\n",
        AUTOSTART, "service_mono_transition_game_thread")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_triview_autostart.py <backend>")
    root = Path(sys.argv[1])
    files = {root / HOOK_HPP: hook_header, root / VR_HPP: vr_header, root / VR_CPP: vr_source}
    out = {p: f(p.read_text(encoding="utf-8")) for p, f in files.items()}
    for p, t in out.items():
        p.write_text(t, encoding="utf-8")
    print("Tri-view B12: saved-ID7 autostart through a Native Stereo Fix warm-up")


if __name__ == "__main__":
    main()
