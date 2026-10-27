#!/usr/bin/env python3
"""Build 2: opt-in binocular UE producer cameras; existing ID6 mono is untouched when OFF.
Apply AFTER the R5 V1 integration, from an exact pinned Joey/UESDK checkout.
No depth synthesis claims are made by this stage.
"""
import pathlib,sys
root=pathlib.Path(sys.argv[1]).resolve()
def edit(path,old,new):
    p=root/path;s=p.read_text(encoding="utf-8-sig")
    count=s.count(old)
    if count!=1:raise RuntimeError(f"binocular refused ambiguous {path}: {count} x {old[:130]}")
    p.write_text(s.replace(old,new,1),encoding="utf-8",newline="")

h="src/mods/VR.hpp"
edit(h,'    const ModToggle::Ptr m_duo_native_fix{ModToggle::create(generate_name("DuoViewNativeFixSamePass"), true)};',
'''    const ModToggle::Ptr m_duo_native_fix{ModToggle::create(generate_name("DuoViewNativeFixSamePass"), true)};
    // OFF preserves the exact Build49+XYZ two-source centered Mono camera.
    const ModToggle::Ptr m_duo_binocular_sources{ModToggle::create(generate_name("DuoViewBinocularSources"), false)};''')
edit(h,'    bool is_duoview_renderer_active() const;',
'''    bool is_duoview_renderer_active() const;
    bool is_duoview_binocular_requested() const {
        return is_duoview_renderer_active() && m_duo_binocular_sources->value();
    }''')
edit(h,'*m_duo_native_fix, *m_duo_quant, *m_duo_hold, *m_duo_reacquire,',
       '*m_duo_native_fix, *m_duo_binocular_sources, *m_duo_quant, *m_duo_hold, *m_duo_reacquire,')

c="src/mods/VR.cpp"
edit(c,'m_duo_native_fix->draw("Native Stereo Fix shading (OFF = stock secondary-pass)");',
'''m_duo_native_fix->draw("Native Stereo Fix shading (OFF = stock secondary-pass)");
                m_duo_binocular_sources->draw("B2: render fovea from LEFT / periphery from RIGHT (EXPERIMENTAL)");
                ImGui::TextWrapped("B2 diagnostic only: switches real UE camera origins, but ID6 still merges both sources into the same output until dual R5 depth and stereo compositing are verified. Turn OFF if images double. Changes take effect only on source frame boundaries.");''')
edit(c,'if (ImGui::Button("Restore old DuoView settings")) {',
'''if (ImGui::Button("Restore old DuoView settings")) {
                    m_duo_binocular_sources->value()=false;''')
edit(c,'auto frame=m_duoview.begin(key, get_hmd_width(), get_hmd_height(), frozen,',
'''auto projection_right = get_projection_matrix(VRRuntime::Eye::RIGHT);
    projection_right[3][2]=near_plane;
    std::array<float,16> frozen_right{};
    std::memcpy(frozen_right.data(), &projection_right[0][0], sizeof(frozen_right));
    auto frame=m_duoview.begin(key, get_hmd_width(), get_hmd_height(), frozen,''')
edit(c,'}, GetTickCount64(), source_frame);',
       '}, GetTickCount64(), source_frame, is_duoview_binocular_requested(), frozen_right);')
f="src/mods/vr/DuoViewState.hpp"
edit(f,'    CameraPose camera{};',
'''    CameraPose camera{};
    std::array<CameraPose, 2> eye_cameras{};
    std::array<float,16> projection_right{};
    bool binocular_enabled{};''')
edit(f,'        if (!frame.rectangles[i] || !frame.projections[i] || !frame.cameras[i]) return {};',
'''        if (!frame.rectangles[i] || !frame.projections[i] || !frame.cameras[i]) return {};
        if (frame.binocular_enabled) {
            for (auto value:frame.eye_cameras[i].position) if (!std::isfinite(value)) return {};
        }''')
edit(f,'    return NativeFrameBinding{frame.config.key, *frame.mono_source_frame};',
'''    if (frame.binocular_enabled) {
        const auto& a=frame.eye_cameras[0].position;
        const auto& b=frame.eye_cameras[1].position;
        const double dx=a[0]-b[0],dy=a[1]-b[1],dz=a[2]-b[2];
        const double ipd_squared=dx*dx+dy*dy+dz*dz;
        // A duplicate pose or physically impossible baseline must not certify true stereo.
        if (!(ipd_squared > 1.e-8 && ipd_squared < 100000000.)) return {};
    }
    return NativeFrameBinding{frame.config.key, *frame.mono_source_frame};''')
edit(f,'matrix[col][row]=frame.projection[col*4+row];',
       'matrix[col][row]=(frame.binocular_enabled && view==1 ? frame.projection_right : frame.projection)[col*4+row];')
edit(f,'        uint64_t now_ms=0, std::optional<uint32_t> mono_source_frame={}) {',
'''        uint64_t now_ms=0, std::optional<uint32_t> mono_source_frame={},
        bool binocular_enabled=false, const std::array<float,16>& projection_right={}) {''')
edit(f,'        slot = ViewFrame{*frozen, projection};',
'''        slot = ViewFrame{*frozen, projection};
        slot->binocular_enabled=binocular_enabled;
        slot->projection_right=projection_right;''')
edit(f,'        return slot->camera;',
       '        return slot->binocular_enabled ? slot->eye_cameras[view] : slot->camera;')
edit(f,'''        if (!slot->camera_valid) { slot->camera = pose; slot->camera_valid = true; }
        else if (slot->camera != pose) { slot->invalid = true; return false; }
        slot->cameras[view] = true;''',
'''        if (slot->binocular_enabled) {
            if (slot->cameras[view] && slot->eye_cameras[view] != pose) {
                slot->invalid=true; return false;
            }
            slot->eye_cameras[view]=pose;
            if (view==0) {slot->camera=pose;slot->camera_valid=true;}
        } else {
            if (!slot->camera_valid) { slot->camera = pose; slot->camera_valid = true; }
            else if (slot->camera != pose) { slot->invalid = true; return false; }
        }
        slot->cameras[view] = true;''')
# Hook: allow the real UEVR Native stereo view transform on the second eye,
# keep frozen view0 replay whenever diagnostic switch is OFF.
f="src/mods/vr/FFakeStereoRenderingHook.cpp"
edit(f,'g_hook->m_has_double_precision && view_index == 1) {',
       'g_hook->m_has_double_precision && view_index == 1 && !vr->is_duoview_binocular_requested()) {')
edit(f,'    const bool mono = vr->is_using_mono();',
       '    const bool mono = vr->is_using_mono() && !vr->is_duoview_binocular_requested();')
edit(f,'        if (vr->is_using_mono()) { true_index = 0; }',
       '        if (vr->is_using_mono() && !vr->is_duoview_binocular_requested()) { true_index = 0; }')
edit(f,'''            if (!vr->duoview_state().camera(key, 0, pose))
                SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView] First scene pose not captured");
        }

        // Modify Player Control Rotation''',
'''            if (!vr->duoview_state().camera(key, 0, pose))
                SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView] First scene pose not captured");
        }
        if (vr->is_duoview_binocular_requested() && g_hook->m_has_double_precision && view_index == 1) {
            const auto key=vr->duoview_producer_key();
            const auto* r=reinterpret_cast<const Rotator<double>*>(view_rotation);
            const auto* p=reinterpret_cast<const Vector3d*>(view_location);
            const uevr::duoview::CameraPose pose{{r->pitch,r->yaw,r->roll},{p->x,p->y,p->z}};
            if (!vr->duoview_state().camera(key,1,pose))
                SPDLOG_WARNING_EVERY_N_SEC(2,"[DuoView][B2] Right-eye camera capture failed");
            else SPDLOG_INFO_EVERY_N_SEC(3,"[DuoView][B2] Two physical UE eye origins captured");
        }

        // Modify Player Control Rotation''')
print("B2: guarded physical left/right UE producer viewpoints, separate projections and per-view pose proof; opt-in OFF retains baseline.")
