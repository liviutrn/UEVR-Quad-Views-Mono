#!/usr/bin/env python3
"""Split-eye source experiment on EXACT DuoView Build 165.
Run AFTER apply_xyz_head_scaling.py, before verify_stage234.py.
No R5, DIBR, depth capture, XR presentation or compositor changes.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_native_split_eye_165.py <pinned-patched-joey-backend>")
root = Path(sys.argv[1]).resolve()
pending = {}

def edit(path, before, after, label):
    path = root / path
    text = pending.get(path, path.read_text(encoding="utf-8-sig"))
    count = text.count(before)
    if count != 1:
        raise RuntimeError(f"{label}: expected one exact anchor in {path}, found {count}")
    pending[path] = text.replace(before, after, 1)

h = "src/mods/VR.hpp"
edit(h,
    '    const ModToggle::Ptr m_duo_native_fix{ModToggle::create(generate_name("DuoViewNativeFixSamePass"), true)};',
    '''    const ModToggle::Ptr m_duo_native_fix{ModToggle::create(generate_name("DuoViewNativeFixSamePass"), true)};
    // Enabled by default only in this isolated experimental Build165 branch.
    // Disabling restores the original Build165 centered producer cameras.
    const ModToggle::Ptr m_duo_split_eye{ModToggle::create(generate_name("DuoView165NativeSplitEye"), true)};''',
    "Add experimental toggle")
edit(h, '    bool is_duoview_renderer_active() const;',
    '''    bool is_duoview_renderer_active() const;
    bool is_duoview_split_eye_enabled() const {
        return is_duoview_renderer_active() && m_duo_split_eye->value();
    }''', "Expose experimental state")
edit(h, '*m_duo_native_fix, *m_duo_quant,',
    '*m_duo_native_fix, *m_duo_split_eye, *m_duo_quant,',
    "Persist experimental toggle")

c = "src/mods/VR.cpp"
edit(c,
    'm_duo_native_fix->draw("Native Stereo Fix shading (OFF = stock secondary-pass)");',
    '''m_duo_native_fix->draw("Native Stereo Fix shading (OFF = stock secondary-pass)");
                m_duo_split_eye->draw("B165 TEST: LEFT fovea / RIGHT periphery native camera");
                ImGui::TextWrapped("ON: Joey native left/right eye origins and projections; left-eye fovea receives cropped projection IN the UE rendering pass. Right-eye periphery uses full projection at reduced resolution. Output is the unchanged SAME combined image for both eyes; visible parallax seams are expected. OFF = original Build165 mono producer cameras. No DIBR.");''',
    "Add diagnostic UI")
edit(c,
    'm_duo_border->value()=false; m_duo_fovea_view->value()=0;',
    'm_duo_border->value()=false; m_duo_fovea_view->value()=0; m_duo_split_eye->value()=false;',
    "Keep Restore old settings as true Build165 A/B")
edit(c,
    'm_duo_fovea_view->draw("Fovea UE source view (0 or 1)");',
    '''if (m_duo_split_eye->value())
                    ImGui::TextUnformatted("Split eye: fixed assignment fovea=UE0 LEFT; periphery=UE1 RIGHT");
                else m_duo_fovea_view->draw("Fovea UE source view (0 or 1)");''',
    "Do not permit swapped physical eyes")
edit(c,
    '''ImGui::TextWrapped("View 0 = FIRST Unreal pass (old prototype default), view 1 = SECOND pass (Build19 default). Identical frozen Mono camera. Switching may reset temporal history.");''',
    '''ImGui::TextWrapped(m_duo_split_eye->value()
                    ? "Native split input: UE0 LEFT cropped FOV, UE1 RIGHT full FOV; final pixels remain MONO identical for both XR eyes."
                    : "Build165 baseline: both UE source passes share the frozen Mono camera.");''',
    "Correct description of sources")
edit(c,
    '    const auto checked=uevr::duoview::reconcile_ui_settings(candidate,current);',
    '''    // Preserve legacy Build165 source-selector expression and validation.
    // The split experiment merely overrides the candidate before it is latched.
    if (m_duo_split_eye->value()) candidate.fovea_view = 0u;
    const auto checked=uevr::duoview::reconcile_ui_settings(candidate,current);''',
    "Freeze native left-eye assignment without altering Build165 selector wiring")
edit(c,
    '''    auto frame=m_duoview.begin(key, get_hmd_width(), get_hmd_height(), frozen,
        [this, frozen, optical]() -> std::optional<uevr::duoview::UV> {''',
    '''    // Important: two native EYE projections, frozen for this producer frame.
    // The left projection is cropped by apply_frame_projection DURING Unreal
    // CalculateStereoProjectionMatrix. This does not render full then crop pixels.
    const bool split_eye = is_duoview_split_eye_enabled();
    std::array<float, 16> frozen_right{};
    if (split_eye) {
        auto right = get_projection_matrix(VRRuntime::Eye::RIGHT);
        right[3][2] = near_plane;
        std::memcpy(frozen_right.data(), &right[0][0], sizeof(frozen_right));
    }
    auto frame=m_duoview.begin(key, get_hmd_width(), get_hmd_height(), frozen,
        [this, frozen, optical]() -> std::optional<uevr::duoview::UV> {''',
    "Use original Joey native right-eye matrix")
edit(c,
    '''}, GetTickCount64(), source_frame);''',
    '''}, GetTickCount64(), source_frame, split_eye, frozen_right);''',
    "Freeze physical eye source policy")

s = "src/mods/vr/DuoViewState.hpp"
edit(s,
    '''    CameraPose camera{};
    std::optional<uint32_t> mono_source_frame{};''',
    '''    CameraPose camera{};
    // Per-source physical UE camera metadata. The existing compositor never
    // consumes this; it is preserved for later DIBR implementation.
    std::array<CameraPose, 2> eye_cameras{};
    std::array<float, 16> projection_right{};
    bool split_eye{};
    std::optional<uint32_t> mono_source_frame{};''',
    "Add frozen stereo producer state")
edit(s,
    '''        if (!frame.rectangles[i] || !frame.projections[i] || !frame.cameras[i]) return {};
    }
    return NativeFrameBinding''',
    '''        if (!frame.rectangles[i] || !frame.projections[i] || !frame.cameras[i]) return {};
    }
    if (frame.split_eye) {
        const auto& l = frame.eye_cameras[0].position;
        const auto& r = frame.eye_cameras[1].position;
        const double dx = l[0]-r[0], dy=l[1]-r[1], dz=l[2]-r[2];
        const double distance_sq = dx*dx + dy*dy + dz*dz;
        // Reject non-finite eye offsets. A zero baseline is diagnosed in logs
        // rather than causing an otherwise good experiment to go black.
        if (!std::isfinite(distance_sq)) return {};
    }
    return NativeFrameBinding''',
    "Validate actual physical camera separation")
edit(s,
    'matrix[col][row]=frame.projection[col*4+row];',
    'matrix[col][row]=(frame.split_eye && view==1 ? frame.projection_right : frame.projection)[col*4+row];',
    "Native right projection; left is cropped by original foveal projection crop")
edit(s,
    '''        uint64_t now_ms=0, std::optional<uint32_t> mono_source_frame={}) {''',
    '''        uint64_t now_ms=0, std::optional<uint32_t> mono_source_frame={},
        bool split_eye=false, const std::array<float,16>& projection_right={}) {''',
    "Freeze mode per source frame")
edit(s,
    '''        for (float x:projection) if (!std::isfinite(x)) return {};''',
    '''        for (float x:projection) if (!std::isfinite(x)) return {};
        if (split_eye)
            for (float x:projection_right) if (!std::isfinite(x)) return {};''',
    "Validate both native projections")
edit(s,
    '''        slot = ViewFrame{*frozen, projection};
        slot->mono_source_frame = mono_source_frame;''',
    '''        slot = ViewFrame{*frozen, projection};
        slot->split_eye = split_eye;
        slot->projection_right = projection_right;
        slot->mono_source_frame = mono_source_frame;''',
    "Attach split input to immutable state")
edit(s,
    '''        return slot->camera;''',
    '''        if (slot->split_eye) return slot->cameras[view]
            ? std::optional<CameraPose>{slot->eye_cameras[view]} : std::nullopt;
        return slot->camera;''',
    "Read per-eye camera")
edit(s,
    '''        if (!slot->camera_valid) { slot->camera = pose; slot->camera_valid = true; }
        else if (slot->camera != pose) { slot->invalid = true; return false; }
        slot->cameras[view] = true;''',
    '''        if (slot->split_eye) {
            if (slot->cameras[view] && slot->eye_cameras[view] != pose) {
                slot->invalid = true; return false;
            }
            slot->eye_cameras[view] = pose;
            if (view == 0) { slot->camera = pose; slot->camera_valid = true; }
        } else {
            if (!slot->camera_valid) { slot->camera = pose; slot->camera_valid = true; }
            else if (slot->camera != pose) { slot->invalid = true; return false; }
        }
        slot->cameras[view] = true;''',
    "Preserve Build165 identical-camera rule when OFF")

hook = "src/mods/vr/FFakeStereoRenderingHook.cpp"
edit(hook,
    '''g_hook->m_has_double_precision && view_index == 1) {''',
    '''g_hook->m_has_double_precision && view_index == 1 && !vr->is_duoview_split_eye_enabled()) {''',
    "Disable only DuoView's second-eye camera overwrite")
edit(hook,
    '''            if (!vr->duoview_state().camera(key, 0, pose))
                SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView] First scene pose not captured");
        }

        // Modify Player Control Rotation''',
    '''            if (!vr->duoview_state().camera(key, 0, pose))
                SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView] First scene pose not captured");
        }
        // Joey native CalculateStereoViewOffset already applied right-eye
        // rotation, IPD and head pose above; capture that output unchanged.
        if (vr->is_duoview_split_eye_enabled() && g_hook->m_has_double_precision && view_index == 1) {
            const auto key = vr->duoview_producer_key();
            const auto* r = reinterpret_cast<const Rotator<double>*>(view_rotation);
            const auto* p = reinterpret_cast<const Vector3d*>(view_location);
            const uevr::duoview::CameraPose pose{{r->pitch,r->yaw,r->roll},{p->x,p->y,p->z}};
            if (!vr->duoview_state().camera(key, 1, pose))
                SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView][Split165] Native right-eye camera not captured");
            else if (const auto snap=vr->duoview_state().snapshot(key)) {
                const auto& a=snap->eye_cameras[0].position;
                const auto& b=snap->eye_cameras[1].position;
                const double dx=a[0]-b[0], dy=a[1]-b[1], dz=a[2]-b[2];
                const double sq=dx*dx+dy*dy+dz*dz;
                SPDLOG_INFO_EVERY_N_SEC(3,
                    "[DuoView][Split165] Native source camera separation squared={:.5f} UE-units^2 (zero implies no physical stereo)",
                    sq);
            }
        }

        // Modify Player Control Rotation''',
    "Capture genuine right-eye result, after native camera handling")

# Fail before changing anything if any original anchor drifted. Once validation
# passes, files are written as a set (not silently skipping unavailable hooks).
for path, contents in pending.items():
    path.write_text(contents, encoding="utf-8", newline="")
print("Build165 SplitEye: real Joey native per-eye input, UE0 cropped left and UE1 full right; existing mono compositor untouched.")
