#!/usr/bin/env python3
"""Tri-view B11: ID7 starts by itself (no Native Stereo Fix detour).

Root cause (source): on STALKER 2 UE5.5.4 DX12, stalker2_uses_lazy_synced_viewstates()
is true unless Native Stereo Fix is active. VR::is_native_stereo_fix_enabled()
returns false whenever ID7 is selected, so the LocalPlayer two-view bootstrap
(PostInitProperties replay) is skipped and ID7 never gets its engine views:
black headset. The user's workaround (Native Stereo + Fix, then ID7) ran that
bootstrap first. DuoView ID6 solved the same problem by reporting Native Fix as
active (apply_stage234.py). B11 does exactly what the workaround did: while ID7
is selected and the bootstrap has not settled, the policy treats ID7 like Native
Stereo Fix; once settled (m_fixed_localplayer_view_count) ID7 continues with the
same lazy path it used after the manual workaround.
Run after apply_triview_bootstrap.py.
"""
from pathlib import Path
import sys

CPP = Path("src/mods/vr/FFakeStereoRenderingHook.cpp")
HPP = Path("src/mods/vr/FFakeStereoRenderingHook.hpp")


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f"cold-start anchor count {text.count(old)}: {old[:100]!r}")
    return text.replace(old, new, 1)


def header(text):
    return once(text,
        "class FFakeStereoRenderingHook : public ModComponent {\npublic:\n",
        "class FFakeStereoRenderingHook : public ModComponent {\npublic:\n"
        "    // Tri-view B11: LocalPlayer two-view bootstrap finished (succeeded or gave up).\n"
        "    bool is_localplayer_bootstrap_settled() const { return m_fixed_localplayer_view_count; }\n")


def source(text):
    start = text.index("bool stalker2_uses_lazy_synced_viewstates() {")
    end = text.index("\n}\n", start)
    body = text[start:end]
    body = once(body,
        "    const auto vr = VR::get();\n"
        "    return vr != nullptr && uevr::vr_compatibility::should_avoid_stalker2_synced_post_init(\n"
        "        true,\n"
        "        vr->is_using_strict_synchronized_afr(),\n"
        "        vr->is_native_stereo_fix_enabled(),\n",
        "    const auto vr = VR::get();\n"
        "    // Tri-view B11 cold start: ID7 runs the Native-Fix LocalPlayer bootstrap first.\n"
        "    const bool qv_cold_bootstrap = vr != nullptr && vr->is_quadview_mode_selected() &&\n"
        "        g_hook != nullptr && !g_hook->is_localplayer_bootstrap_settled();\n"
        "    static std::atomic<int> qv_cold_logged{-1};\n"
        "    if (vr != nullptr && vr->is_quadview_mode_selected() && qv_cold_logged.exchange(qv_cold_bootstrap ? 1 : 0) != (qv_cold_bootstrap ? 1 : 0)) {\n"
        "        SPDLOG_INFO(\"[TriView][ColdStart] LocalPlayer bootstrap {}\", qv_cold_bootstrap ? \"pending: Native-Fix allocator path\" : \"settled: lazy synced path\");\n"
        "    }\n"
        "    return vr != nullptr && uevr::vr_compatibility::should_avoid_stalker2_synced_post_init(\n"
        "        true,\n"
        "        vr->is_using_strict_synchronized_afr(),\n"
        "        vr->is_native_stereo_fix_enabled() || qv_cold_bootstrap,\n")
    return text[:start] + body + text[end:]


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_triview_coldstart.py <backend>")
    root = Path(sys.argv[1])
    h, c = root / HPP, root / CPP
    hs, cs = header(h.read_text(encoding="utf-8")), source(c.read_text(encoding="utf-8"))
    h.write_text(hs, encoding="utf-8"); c.write_text(cs, encoding="utf-8")
    print("Tri-view B11: ID7 cold-start LocalPlayer bootstrap enabled")


if __name__ == "__main__":
    main()
