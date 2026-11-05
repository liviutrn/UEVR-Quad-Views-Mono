#!/usr/bin/env python3
"""Tri-view B12: make-before-break resize of the TriView source targets.

Evidence (B11 log 2026-11-06): changing the periphery resolution unpublished the
live per-role target set immediately (ensure_quadview_native_target_set stored
nullptr), so frames fell back to the full-size atlas path until the new set was
published (+850 MB VRAM transient at 00:59:32) and the first periphery resize
crashed 20 ms into that window. B12 never leaves that window:
- ensure() keeps the old set published while the new one is built in the same
  world (a world change still unpublishes at once, the old actors are gone);
- the draw keeps the last live sizes (crop, periphery scale, density) until the
  new set is published, while requesting the new extents; then it switches.
Run after apply_triview_compact.py.
"""
from pathlib import Path
import sys

VR_CPP = Path("src/mods/VR.cpp")
VR_HPP = Path("src/mods/VR.hpp")
HOOK_CPP = Path("src/mods/vr/FFakeStereoRenderingHook.cpp")


def once(text, old, new, what):
    if text.count(old) != 1:
        raise RuntimeError(f"resize anchor ({what}) count {text.count(old)}")
    return text.replace(old, new, 1)


def hook_source(text):
    return once(text,
        "        quadview_native_target_build=build;\n"
        "        quadview_native_target_set_snapshot.store(nullptr,std::memory_order_release);\n",
        "        quadview_native_target_build=build;\n"
        "        // Tri-view B12 make-before-break: same world -> keep drawing with the old\n"
        "        // set until this build publishes; another world -> its actors are gone.\n"
        "        if (const auto old=quadview_native_target_set_snapshot.load(std::memory_order_acquire);\n"
        "            !old || old->world_identity!=world_identity || !old->complete())\n"
        "            quadview_native_target_set_snapshot.store(nullptr,std::memory_order_release);\n",
        "ensure unpublish")


def vr_header(text):
    return once(text,
        "    int m_triview_autostart_stage{0};\n",
        "    int m_triview_autostart_stage{0};\n"
        "    // Tri-view B12 make-before-break resize (game thread only).\n"
        "    struct TriViewLiveSizes { float crop_width{}, crop_height{}, context_scale{}, foveal_density{}; bool valid{}; } m_triview_live_sizes{};\n"
        "    std::array<std::array<uint32_t,2>,4> m_triview_pending_extents{};\n"
        "    bool m_triview_pending_extents_valid{false};\n",
        "vr members")


OVERRIDE = r'''            // Tri-view B12 make-before-break: while new sizes have no published target
            // set yet, draw with the last live sizes and only request the new extents.
            m_triview_pending_extents_valid=false;
            if (m_quadview_compact_targets->value() && m_triview_live_sizes.valid) {
                const auto live_rtm=m_fake_stereo_hook->get_render_target_manager();
                const auto live=live_rtm ? live_rtm->get_quadview_native_target_set() : nullptr;
                auto wanted=uevr::quadview::make_layout(width,height,draw_config.settings.crop_width,
                    draw_config.settings.crop_height,draw_config.settings.context_scale,draw_config.settings.foveal_density,focus);
                if (wanted && live && live->complete() && uevr::quadview::apply_native_local(*wanted) &&
                    uevr::quadview::source_extents(*wanted)!=live->extents) {
                    m_triview_pending_extents=uevr::quadview::source_extents(*wanted);
                    m_triview_pending_extents_valid=true;
                    draw_config.settings.crop_width=m_triview_live_sizes.crop_width;
                    draw_config.settings.crop_height=m_triview_live_sizes.crop_height;
                    draw_config.settings.context_scale=m_triview_live_sizes.context_scale;
                    draw_config.settings.foveal_density=m_triview_live_sizes.foveal_density;
                    SPDLOG_INFO_EVERY_N_SEC(1,"[TriView][Resize] new source sizes {}x{} / {}x{} requested; drawing with the live set until it is published",
                        m_triview_pending_extents[0][0],m_triview_pending_extents[0][1],m_triview_pending_extents[2][0],m_triview_pending_extents[2][1]);
                }
            }
            auto candidate=uevr::quadview::make_layout(width,height,draw_config.settings.crop_width,
'''


def vr_source(text):
    text = once(text,
        "            auto candidate=uevr::quadview::make_layout(width,height,draw_config.settings.crop_width,\n",
        OVERRIDE, "candidate")
    text = once(text,
        "                    if (set && set->extents==uevr::quadview::source_extents(compact) && set->complete()) *candidate=compact;\n",
        "                    if (set && set->extents==uevr::quadview::source_extents(compact) && set->complete()) {\n"
        "                        *candidate=compact;\n"
        "                        m_triview_live_sizes={draw_config.settings.crop_width,draw_config.settings.crop_height,\n"
        "                            draw_config.settings.context_scale,draw_config.settings.foveal_density,true};\n"
        "                    }\n", "compact select")
    text = once(text,
        "        if (uevr::quadview::apply_native_local(compact)) requested_extents=uevr::quadview::source_extents(compact);\n"
        "    }\n",
        "        if (uevr::quadview::apply_native_local(compact)) requested_extents=uevr::quadview::source_extents(compact);\n"
        "    }\n"
        "    if (m_quadview_compact_targets->value() && m_triview_pending_extents_valid) requested_extents=m_triview_pending_extents;\n",
        "requested extents")
    text = once(text,
        "    if (rtm && is_quadview_supported_title() && rtm->ensure_quadview_native_target_set(requested_extents))\n"
        "        native_target_set=rtm->get_quadview_native_target_set();\n",
        "    if (rtm && is_quadview_supported_title() && rtm->ensure_quadview_native_target_set(requested_extents))\n"
        "        native_target_set=rtm->get_quadview_native_target_set();\n"
        "    else if (rtm && m_triview_pending_extents_valid) {\n"
        "        // B12: the new set is still building; keep drawing from the old live set.\n"
        "        const auto live=rtm->get_quadview_native_target_set();\n"
        "        if (live && live->complete() && live->extents==uevr::quadview::source_extents(*layout) &&\n"
        "            rtm->quadview_native_targets_live(*live)) native_target_set=live;\n"
        "    }\n", "keep live set")
    return text


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_triview_resize_safety.py <backend>")
    root = Path(sys.argv[1])
    files = {root / HOOK_CPP: hook_source, root / VR_HPP: vr_header, root / VR_CPP: vr_source}
    out = {p: f(p.read_text(encoding="utf-8")) for p, f in files.items()}
    for p, t in out.items():
        p.write_text(t, encoding="utf-8")
    print("Tri-view B12: make-before-break source target resize")


if __name__ == "__main__":
    main()
