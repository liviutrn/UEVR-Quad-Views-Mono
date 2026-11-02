#!/usr/bin/env python3
"""Apply v210 manual NGX depth browser after v209. Metadata-only DX12 hooks.

No textures/COM resources are retained, no shader changes and no synthetic stereo.
"""
from pathlib import Path
import sys


def only_once(value, old, new, name):
    count = value.count(old)
    if count != 1:
        raise RuntimeError(f"{name} exact anchor count={count}: {old[:80]!r}")
    return value.replace(old, new, 1)


def apply(root, source):
    dx = root / "src/mods/vr/D3D12Component.cpp"
    vr = root / "src/mods/VR.cpp"
    old_dx = dx.read_text(encoding="utf-8-sig")
    old_vr = vr.read_text(encoding="utf-8-sig")
    new_dx = only_once(old_dx, '#include "D3D12Component.hpp"',
        '#include "D3D12Component.hpp"\n#include "d3d12/DuoViewNgxManualObserver.hpp"', "D3D12Component.cpp")
    new_dx = only_once(new_dx, 'void D3D12Component::on_post_present(VR* vr) {\n',
        """void D3D12Component::on_post_present(VR* vr) {
    // Install a late-load-safe NGX-SR metadata observer in STALKER 2 DuoView only.
    // Every original NVIDIA evaluate still runs unchanged. No borrowed GPU
    // resource survives the native evaluate callback.
    auto& ngx_depth_browser=uevr::duoview::ngx::ManualNgxObserver::self();
    const bool browser_active=vr && vr->is_duoview_renderer_active();
    ngx_depth_browser.set_active(browser_active);
    if (browser_active) ngx_depth_browser.install();
""", "D3D12Component.cpp")
    new_vr = only_once(old_vr, '#include "VR.hpp"\n#include <cstring>',
        '#include "VR.hpp"\n#include <cstring>\n#include "vr/DuoViewNgxManualDepth.hpp"',
        "VR.cpp")

    new_vr = only_once(new_vr,
        '                m_duo_distance_smooth->draw("Future smooth transition (OFF = linear)");',
        '''                m_duo_distance_smooth->draw("Future smooth transition (OFF = linear)");
                if (ImGui::CollapsingHeader("DLSS fovea depth sources (v210 manual selection)")) {
                    ImGui::TextWrapped("Native NGX-SR depth sources are now OBSERVED and can be manually pinned. This browser does not yet copy or sample the depth pixels. Distance sharpening still uses fixed strength until matching the producing fovea is proven.");
                    const auto found=uevr::duoview::ngx::candidates().browse();
                    const auto pin=uevr::duoview::ngx::candidates().selected();
                    ImGui::Text("Observed candidates: %zu; configured fovea UE view: %d",
                        found.size(),m_duo_fovea_view->value());
                    if (ImGui::Button("Clear selected NGX depth source"))
                        uevr::duoview::ngx::candidates().clear();
                    for (const auto& c : found) {
                        const auto age=uevr::duoview::ngx::candidates().age_ms(c);
                        if(age>15000)continue;
                        ImGui::PushID(static_cast<int>(c.serial));
                        const bool pinned=pin[0]==c.feature &&
                            pin[1]==c.output_width && pin[2]==c.output_height;
                        ImGui::Text("NGX %llu: 0x%llx output=%ux%u input=%ux%u depth=%ux%u format=%u",
                            static_cast<unsigned long long>(c.serial),
                            static_cast<unsigned long long>(c.feature),
                            c.output_width,c.output_height,c.render_width,c.render_height,
                            c.depth_width,c.depth_height,c.format);
                        ImGui::Text("kind=%s jitter=(%.3f,%.3f) depth base=(%u,%u), age=%llums%s",
                            c.create_observed ? (c.feature_kind==1?"SR":"other") : "unverified SR-like",
                            c.jitter_x,c.jitter_y,c.depth_x,c.depth_y,
                            static_cast<unsigned long long>(age),pinned?" PINNED":"");
                        if(age<=3000 && ImGui::Button("Pin this as fovea depth")) {
                            uevr::duoview::ngx::candidates().pin(
                                c.feature,c.output_width,c.output_height);
                        }
                        ImGui::Separator();
                        ImGui::PopID();
                    }
                }''', "VR.cpp")
    copies = {
        root / "src/mods/vr/DuoViewNgxManualDepth.hpp":
            source / "DuoViewNgxManualDepth.hpp",
        root / "src/mods/vr/d3d12/DuoViewNgxManualObserver.hpp":
            source / "DuoViewNgxManualObserver.hpp",
    }
    for dst, src in copies.items():
        if dst.exists():
            raise RuntimeError("Refusing overwrite: " + str(dst))
        if not src.is_file():
            raise RuntimeError("Missing pinned source: " + str(src))
    dx.write_text(new_dx, encoding="utf-8", newline="")
    vr.write_text(new_vr, encoding="utf-8", newline="")
    for dst, src in copies.items():
        dst.write_bytes(src.read_bytes())
    print("PASS: v210 manual NGX depth observer/selector installed; GPU captures/compositor untouched")


if __name__ == "__main__":
    if len(sys.argv)!=3:
        raise SystemExit("Usage: apply_v210_ngx_manual.py BACKEND DUOVIEW_SOURCE")
    apply(Path(sys.argv[1]), Path(sys.argv[2]))
