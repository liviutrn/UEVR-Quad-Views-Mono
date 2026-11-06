#!/usr/bin/env python3
"""TriView B17: three physical UE render targets (0,2,3) and original menu wheel.

Apply ONLY after the complete tested B15 overlay chain. Logical view 1 remains
in the four-view *view-family* ABI and GPU shader descriptor table, but has no
UE actor, texture, RHI target or physical render. Shader SRV 1 aliases periphery
SRV 0 (shader ContextSource.y is already zero for TriView).

Do not merge this with B16: B16's nested UI and unproven resize throttle are not
used. The B14/B15 source-set retirement, pose, reprojection and menu remain.
"""
from pathlib import Path
import sys


def one(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"B17 {label}: expected one anchor, found {count}: {old[:130]!r}")
    return text.replace(old, new, 1)


def one_file(path, transform):
    before = path.read_text(encoding="utf-8")
    after = transform(before)
    if after == before:
        raise RuntimeError(f"B17 no changes to {path}")
    path.write_text(after, encoding="utf-8", newline="\n")


def vr_cpp(s):
    # Force native-local, shared-center TriView, regardless of old saved QuadView
    # or compact-source toggle states. Do not expose an unsafe QuadView fallback.
    if not s.count('m_quadview_tri_view->value()'):
        raise RuntimeError("B17 missing TriView layout switch")
    s = s.replace('m_quadview_tri_view->value()', 'true')
    if not s.count('m_quadview_compact_targets->value()'):
        raise RuntimeError("B17 missing native-local switch")
    s = s.replace('m_quadview_compact_targets->value()', 'true')
    s = one(s,
        '                m_quadview_tri_view->draw("Tri-view: one shared centre periphery (3 renders; OFF = 4)");\n',
        '                ImGui::TextUnformatted("TriView: shared periphery + two stereo foveas (3 physical sources)");\n',
        "remove legacy QuadView mode checkbox")
    s = one(s,
        '                m_quadview_compact_targets->draw("Compact source textures (saves video memory; OFF = B5 full-size textures)");\n',
        '                ImGui::TextUnformatted("Compact sources: always on");\n',
        "remove large atlas toggle")
    if 'uevr::quadview::source_extents(' not in s:
        raise RuntimeError("B17 missing source extents path")
    s = s.replace('uevr::quadview::source_extents(', 'uevr::quadview::triview_source_extents(')
    # Invalid/missing synchronized stage poses cannot fall back to four physical
    # source renders. B15's pose and recenter path remains untouched.
    s = one(s,
        '    const auto rtm = m_fake_stereo_hook->get_render_target_manager();\n'
        '    std::shared_ptr<const VRRenderTargetManager_Base::QuadViewNativeTargetSetSnapshot> native_target_set{};',
        '    if (!layout->shared_context) {\n'
        '        set_quadview_status("TriView requires a valid shared periphery pose; skipping this draw (QuadView fallback disabled)");\n'
        '        return {};\n'
        '    }\n'
        '    const auto rtm = m_fake_stereo_hook->get_render_target_manager();\n'
        '    std::shared_ptr<const VRRenderTargetManager_Base::QuadViewNativeTargetSetSnapshot> native_target_set{};',
        "fail-closed TriView layout")
    return s


def vr_header(s):
    s = one(s,
        '            for (size_t i=0;i!=4;++i) {\n'
        '                const auto& owner=target_owners[i];\n'
        '                const auto& native=native_sources[i];',
        '            for (size_t i=0;i!=4;++i) {\n'
        '                if (i==1) {\n'
        '                    if (target_owners[i] || render_targets[i] || native_sources[i]) return false;\n'
        '                    continue;\n'
        '                }\n'
        '                const auto& owner=target_owners[i];\n'
        '                const auto& native=native_sources[i];',
        "skip dormant target in snapshot complete")
    s = one(s,
        'uevr::quadview::valid_native_target_roles(identities,extents)',
        'uevr::quadview::valid_native_triview_targets(identities,extents)',
        "validate exactly three native identities")
    return s


def hook_cpp(s):
    # Once *every* backend caller uses the TriView helper, the idle target has
    # zero extents. Explicitly reject accidental four-target requests.
    if 'uevr::quadview::source_extents(' not in s:
        raise RuntimeError("B17 missing native source-extents gate")
    s = s.replace('uevr::quadview::source_extents(', 'uevr::quadview::triview_source_extents(')
    s = one(s,
        '    for (size_t i=0;i!=4;++i) {\n'
        '        const auto& snapshot=targets.target_owners[i];',
        '    for (size_t i=0;i!=4;++i) {\n'
        '        if (i==1) continue; // No physical right periphery in TriView.\n'
        '        const auto& snapshot=targets.target_owners[i];',
        "physical target lifetime gate")
    s = one(s,
        '    const bool extents_valid=std::all_of(extents.begin(),extents.end(),[](const auto& e) {\n'
        '        return e[0] && e[1] && e[0]<=16384 && e[1]<=8192; });',
        '    constexpr std::array<size_t,3> tri_roles{0,2,3};\n'
        '    const bool extents_valid=extents[1][0]==0 && extents[1][1]==0 &&\n'
        '        std::all_of(tri_roles.begin(),tri_roles.end(),[&](size_t i) {\n'
        '            const auto& e=extents[i];\n'
        '            return e[0] && e[1] && e[0]<=16384 && e[1]<=8192;\n'
        '        });',
        "reject a fourth physical extent")
    s = one(s,
        '        for (size_t i=0;i!=4;++i) {\n'
        '            auto owner=std::shared_ptr<QuadViewNativeTargetOwner>',
        '        for (size_t i=0;i!=4;++i) {\n'
        '            if (i==1) continue; // Do not spawn a holder or allocate a texture.\n'
        '            auto owner=std::shared_ptr<QuadViewNativeTargetOwner>',
        "three Kismet allocations")
    s = one(s,
        '        for (size_t i=0;i!=4;++i) {\n'
        '            const auto& owner=build->owners[i];',
        '        for (size_t i=0;i!=4;++i) {\n'
        '            if (i==1) continue;\n'
        '            const auto& owner=build->owners[i];',
        "validate three texture chains")
    s = one(s,
        '        for (size_t i=0;i!=4;++i) {\n'
        '            auto& owner=*build->owners[i]; auto* frt=chains[i].render_target;',
        '        for (size_t i=0;i!=4;++i) {\n'
        '            if (i==1) continue;\n'
        '            auto& owner=*build->owners[i]; auto* frt=chains[i].render_target;',
        "publish three native targets")
    s = one(s,
        'SPDLOG_INFO("[QuadViews][NativeFix] Published four independent UE5.5 source targets {}x{} {}x{} {}x{} {}x{} generation={}",',
        'SPDLOG_INFO("[TriView][NativeFix] Published THREE independent UE5.5 source targets {}x{} (unused: {}x{}) {}x{} {}x{} generation={}",',
        "correct target count in audit log")
    return s


def native_delivery_header(s):
    # B18: canonical source and tests now use the same required-role behavior.
    # Keep a guarded verification here so replay cannot silently diverge.
    if 'if ((required_roles & uint8_t(1u << i)) == 0) continue;' not in s or \
            'slot.roles_bound = required_roles;' not in s:
        raise RuntimeError("Canonical NativeDelivery lacks the three-role contract")
    return s


def d3d12_consumer(s):
    s = one(s,
        '                                native_sources[i]=isolated ? packet->native_sources[i].Get() : packet->atlas.Get();\n'
        '                                if (!native_sources[i]) sources_valid=false;\n'
        '                                if (isolated) for (size_t j=0; j<i; ++j)\n'
        '                                    if (native_sources[i]==native_sources[j]) sources_valid=false;',
        '                                // Slot 1 is a shader descriptor alias only. It is NOT a fourth UE target.\n'
        '                                native_sources[i]=isolated\n'
        '                                    ? (frozen->layout.shared_context && i==1\n'
        '                                        ? packet->native_sources[0].Get() : packet->native_sources[i].Get())\n'
        '                                    : packet->atlas.Get();\n'
        '                                if (!native_sources[i]) sources_valid=false;\n'
        '                                if (isolated && i!=1) for (size_t j=0; j<i; ++j)\n'
        '                                    if (j!=1 && native_sources[i]==native_sources[j]) sources_valid=false;',
        "shader input alias without physical allocation")
    return s


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_triview_b17.py <backend>")
    base = Path(sys.argv[1]) / "src/mods"
    ops = {
        base/"VR.cpp": vr_cpp,
        base/"vr/FFakeStereoRenderingHook.hpp": vr_header,
        base/"vr/FFakeStereoRenderingHook.cpp": hook_cpp,
        base/"vr/QuadViewNativeDelivery.hpp": native_delivery_header,
        base/"vr/D3D12Component.cpp": d3d12_consumer,
    }
    # Validate all anchors in memory before changing any generated source.
    results = {p: transform(p.read_text(encoding="utf-8")) for p, transform in ops.items()}
    for p, result in results.items():
        p.write_text(result, encoding="utf-8", newline="\n")
    print("B17: three physical slots 0/2/3; shader slot 1 aliases 0; original menu wheel; no QuadView mode")


if __name__ == "__main__":
    main()
