#!/usr/bin/env python3
"""B28: bind ID7 context cameras and projection submission to one located pose.

Apply to a fully materialized B23 backend. Does not alter any other mode.
"""
from pathlib import Path
import sys

root = Path(sys.argv[1])
changes = {}
def edit(name, old, new):
    path = root / name
    data = changes.get(path, path.read_text(encoding='utf-8'))
    n = data.count(old)
    if n != 1:
        raise RuntimeError(f'{name}: expected 1 anchor, got {n}: {old[:120]!r}')
    changes[path] = data.replace(old, new, 1)

h='src/mods/vr/runtimes/OpenXR.hpp'
c='src/mods/vr/runtimes/OpenXR.cpp'
v='src/mods/VR.hpp'
vc='src/mods/VR.cpp'
f='src/mods/vr/FFakeStereoRenderingHook.cpp'
edit(h, '#include "../QuadViewGeometry.hpp"', '#include "../QuadViewGeometry.hpp"\n#include "../TriViewLocatedPose.hpp"')
edit(h, '        bool quadview_pose_valid{};\n', '''        bool quadview_pose_valid{};
        uint64_t quadview_locate_serial{}; // Assigned only to a completed locate, never a scene-role stamp.
        std::array<XrView,2> quadview_head_views{};
''')
edit(h, '    std::optional<PipelineState> capture_quadview_pose(uint32_t frame);', '''    // Protected by sync_assignment_mtx. Scene-role frame stamps never mutate this copy.
    uevr::triview::LocatedPose<PipelineState> quadview_latest_located_pose{};
    void invalidate_quadview_located_pose();
    std::optional<PipelineState> capture_quadview_pose(uint32_t frame);''')
edit(c, '''    const auto finish_pose_update = [&](VRRuntime::Error result) -> VRRuntime::Error {
        const auto now = std::chrono::steady_clock::now();''', '''    const auto finish_pose_update = [&](VRRuntime::Error result) -> VRRuntime::Error {
        if (vr->is_quadview_mode_selected() && result!=VRRuntime::Error::SUCCESS)
            quadview_latest_located_pose.invalidate();
        const auto now = std::chrono::steady_clock::now();''')
edit(c, '''    view_locate_info = {XR_TYPE_VIEW_LOCATE_INFO};
    view_locate_info.viewConfigurationType = this->view_config;
    view_locate_info.displayTime = display_time;
    view_locate_info.space = this->stage_space;''', '''    const uint32_t quadview_head_view_count=view_count;
    view_locate_info = {XR_TYPE_VIEW_LOCATE_INFO};
    view_locate_info.viewConfigurationType = this->view_config;
    view_locate_info.displayTime = display_time;
    view_locate_info.space = this->stage_space;''')
edit(c, '''        pipeline_state.quadview_pose_valid=view_count==2 &&
            (this->stage_view_state.viewStateFlags & flags)==flags &&
            (this->view_state.viewStateFlags & flags)==flags;
''', '''        pipeline_state.quadview_pose_valid=view_count==2 && quadview_head_view_count==2 && this->views.size()==2 &&
            this->stage_views.size()==2 &&
            (this->stage_view_state.viewStateFlags & flags)==flags &&
            (this->view_state.viewStateFlags & flags)==flags &&
            (this->view_space_location.locationFlags &
                (XR_SPACE_LOCATION_ORIENTATION_VALID_BIT | XR_SPACE_LOCATION_POSITION_VALID_BIT)) ==
                (XR_SPACE_LOCATION_ORIENTATION_VALID_BIT | XR_SPACE_LOCATION_POSITION_VALID_BIT);
        if (pipeline_state.quadview_pose_valid) {
            pipeline_state.quadview_head_views={this->views[0],this->views[1]};
            quadview_latest_located_pose.publish(pipeline_state);
        } else {
            quadview_latest_located_pose.invalidate();
        }
''')
# The old reader selects by a mutable scene-role frame number.  The new source is
# only assigned after all required locate calls completed successfully.
start='''    const auto frame=this->internal_frame_count;
    const auto& pose=this->pipeline_states[frame%QUEUE_SIZE];
    if (pose.frame_count!=frame || pose.stage_views.size()!=2 || !pose.quadview_pose_valid ||
        pose.frame_state.predictedDisplayTime<=0 || pose.frame_state.shouldRender!=XR_TRUE) return {};
'''
edit(c, start, '''    if (!quadview_latest_located_pose.get()) return {};
    const auto& pose=*quadview_latest_located_pose.get();
    if (!pose.quadview_locate_serial || pose.stage_views.size()!=2 || !pose.quadview_pose_valid ||
        pose.frame_state.predictedDisplayTime<=0 || pose.frame_state.shouldRender!=XR_TRUE) return {};
''')
edit(c, '''    return pose;
}

void OpenXR::invalidate_quadview_scene() {''', '''    const auto& hp=pose.view_space_location.pose.position;
    if (!std::isfinite(hp.x) || !std::isfinite(hp.y) || !std::isfinite(hp.z)) return {};
    for (const auto& view : pose.quadview_head_views) {
        const auto& p=view.pose.position; const auto& q=view.pose.orientation;
        const double norm=double(q.x)*q.x+double(q.y)*q.y+double(q.z)*q.z+double(q.w)*q.w;
        if (!std::isfinite(p.x) || !std::isfinite(p.y) || !std::isfinite(p.z) ||
            !std::isfinite(norm) || std::abs(norm-1.0)>.01) return {};
    }
    return pose;
}

void OpenXR::invalidate_quadview_scene() {''')
edit(c, '''void OpenXR::reset_mono_projection_history() {
    std::scoped_lock lock{this->sync_assignment_mtx, this->pose_mtx};
    mono_frames = {};''', '''void OpenXR::reset_mono_projection_history() {
    std::scoped_lock lock{this->sync_assignment_mtx, this->pose_mtx};
    invalidate_quadview_located_pose();
    mono_frames = {};''')
edit(c, 'void OpenXR::invalidate_quadview_scene() {', '''void OpenXR::invalidate_quadview_located_pose() {
    std::scoped_lock lock{this->sync_assignment_mtx};
    quadview_latest_located_pose.invalidate();
    triview_pose_redirect=false;
    triview_pose_located=false;
    triview_newest_pose_frame=0;
    triview_newest_pose_location={XR_TYPE_SPACE_LOCATION};
}

void OpenXR::invalidate_quadview_scene() {''')
# Latest head getter is independent of role-number rollback or recycled ring slots.
edit(h, '''        const auto frame = uevr::quadview::current_pose_frame(this->triview_pose_redirect,
            this->triview_pose_located, internal_frame_count, this->triview_newest_pose_frame);
        if (frame != internal_frame_count && this->pipeline_states[frame % QUEUE_SIZE].frame_count != frame) {
            return this->triview_newest_pose_location;
        }
        return get_view_space_location(frame);''', '''        if (triview_pose_redirect && quadview_latest_located_pose.get()) {
            return quadview_latest_located_pose.get()->view_space_location;
        }
        return get_view_space_location(internal_frame_count);''')
edit(vc, '''            const auto frame=m_openxr ? m_openxr->internal_frame_count : 0u;
            std::optional<runtimes::OpenXR::PipelineState> pose;
            if (m_openxr && frame) pose=m_openxr->capture_quadview_pose(frame);''', '''            std::optional<runtimes::OpenXR::PipelineState> pose;
            if (m_openxr) pose=m_openxr->capture_quadview_current_pose();''')
edit(vc, '''                0.5*std::abs(double(get_eye_offset(VRRuntime::Eye::RIGHT).x)-double(get_eye_offset(VRRuntime::Eye::LEFT).x))*
                    double(get_world_to_meters()),''', '''                0.5*std::abs(pose
                    ? double(pose->quadview_head_views[1].pose.position.x)-double(pose->quadview_head_views[0].pose.position.x)
                    : double(get_eye_offset(VRRuntime::Eye::RIGHT).x)-double(get_eye_offset(VRRuntime::Eye::LEFT).x))*
                    double(get_world_to_meters()),''')
edit(v, '''    bool quadview_note_eye_pose(uint32_t eye) {''', '''    // Available before either context eye is marked complete. Used only by
    // the current ID7 draw's camera calculation, never by general HMD queries.
    struct QuadViewCameraPose {
        XrSpaceLocation view_space_location{XR_TYPE_SPACE_LOCATION};
        std::array<XrView,2> quadview_head_views{};
        uint64_t quadview_locate_serial{};
    };
    std::optional<QuadViewCameraPose> quadview_camera_pose() const {
        const auto key=quadview_key();
        std::scoped_lock lock{m_quadview_pose_mutex};
        if (m_quadview_pose_key!=key || !m_quadview_pose) return std::nullopt;
        return QuadViewCameraPose{m_quadview_pose->view_space_location,
            m_quadview_pose->quadview_head_views,m_quadview_pose->quadview_locate_serial};
    }
    bool quadview_note_eye_pose(uint32_t eye) {''')
edit(v, "bool quadview_note_eye_pose(uint32_t eye) {", "bool quadview_note_eye_pose(uint32_t eye, uint64_t located_serial) {")
# The same immutable snapshot is used by the camera and its source packet.
# A later successful locate must not invalidate a sound in-flight draw.
edit(v, '''        const auto current=m_openxr->capture_quadview_current_pose();
        if (!current || current->frame_count!=m_quadview_pose->frame_count ||''', '''        if (!located_serial || located_serial!=m_quadview_pose->quadview_locate_serial) return false;
        m_quadview_pose_eye_mask |= static_cast<uint8_t>(1u << eye);
        return true;
    }
    /* B28 removed comparison with the moving latest locate.
        if (!current || current->frame_count!=m_quadview_pose->frame_count ||''')
edit(v, '''        m_quadview_pose_eye_mask |= static_cast<uint8_t>(1u << eye);
        return true;
    }
    std::optional<runtimes::OpenXR::PipelineState> quadview_frozen_pose''', '''        m_quadview_pose_eye_mask |= static_cast<uint8_t>(1u << eye);
        return true;
    } */
    std::optional<runtimes::OpenXR::PipelineState> quadview_frozen_pose''')
edit(f, '''    const auto view_d = (Vector3d*)view_location;''', '''    const auto qv_pose = quadview_active && view_index >= 0 && view_index <= 1
        ? vr->quadview_camera_pose() : std::optional<VR::QuadViewCameraPose>{};
    const auto view_d = (Vector3d*)view_location;''')
edit(f, '''            if (!vr->quadview_note_eye_pose(static_cast<uint32_t>(view_index)))''', '''            if (!vr->quadview_note_eye_pose(static_cast<uint32_t>(view_index),
                    qv_pose ? qv_pose->quadview_locate_serial : 0))''')
# Use the same frozen head and head-space eye transforms that will be submitted.
edit(f, '''        const auto rotation_offset = vr->get_rotation_offset();
        const auto current_hmd_rotation = glm::normalize(rotation_offset * glm::quat{vr->get_rotation(0)});
        const auto current_eye_rotation_offset = glm::normalize(glm::quat{vr->get_eye_transform(true_index)});

        const auto new_rotation = glm::normalize(vqi_norm * current_hmd_rotation * current_eye_rotation_offset);
        const auto eye_offset = mono
            ? (glm::vec3{vr->get_eye_offset(VRRuntime::Eye::LEFT)} + glm::vec3{vr->get_eye_offset(VRRuntime::Eye::RIGHT)}) * 0.5f
            : glm::vec3{vr->get_eye_offset((VRRuntime::Eye)(true_index))};


        const auto standing_delta = vr->get_position(0) - vr->get_standing_origin();''', '''        const auto rotation_offset = vr->get_rotation_offset();
        const auto qv_eye_matrix = [&](uint32_t eye) {
            const auto& p=qv_pose->quadview_head_views[eye].pose;
            auto m=Matrix4x4f{runtimes::OpenXR::to_glm(p.orientation)};
            m[3]=Vector4f{p.position.x,p.position.y,p.position.z,1.0f};
            return m;
        };
        const auto head_rotation=qv_pose
            ? glm::quat{runtimes::OpenXR::to_glm(qv_pose->view_space_location.pose.orientation)}
            : glm::quat{vr->get_rotation(0)};
        const auto current_hmd_rotation = glm::normalize(rotation_offset * head_rotation);
        const auto current_eye_rotation_offset = glm::normalize(glm::quat{qv_pose
            ? qv_eye_matrix(static_cast<uint32_t>(true_index)) : vr->get_eye_transform(true_index)});

        const auto new_rotation = glm::normalize(vqi_norm * current_hmd_rotation * current_eye_rotation_offset);
        const auto eye_offset = mono
            ? (glm::vec3{vr->get_eye_offset(VRRuntime::Eye::LEFT)} + glm::vec3{vr->get_eye_offset(VRRuntime::Eye::RIGHT)}) * 0.5f
            : glm::vec3{qv_pose ? qv_eye_matrix(static_cast<uint32_t>(true_index))[3]
                                : vr->get_eye_offset((VRRuntime::Eye)(true_index))};

        const auto head_position=qv_pose
            ? Vector4f{qv_pose->view_space_location.pose.position.x,qv_pose->view_space_location.pose.position.y,
                       qv_pose->view_space_location.pose.position.z,1.0f}
            : vr->get_position(0);
        const auto standing_delta = head_position - vr->get_standing_origin();''')
edit(f, '''            const auto center_offset = (glm::vec3{vr->get_eye_offset(VRRuntime::Eye::LEFT)} +
                glm::vec3{vr->get_eye_offset(VRRuntime::Eye::RIGHT)}) * 0.5f;''', '''            const auto center_offset = qv_pose
                ? (glm::vec3{qv_eye_matrix(0)[3]} + glm::vec3{qv_eye_matrix(1)[3]}) * 0.5f
                : (glm::vec3{vr->get_eye_offset(VRRuntime::Eye::LEFT)} +
                   glm::vec3{vr->get_eye_offset(VRRuntime::Eye::RIGHT)}) * 0.5f;''')
# OpenXR eye positions are in head space; cant changes optical rotation, not
# the translation basis. Preserve the inherited formula in every other mode.
edit(f, '''        const auto eye_translation_rotation = mono ? glm::normalize(vqi_norm * current_hmd_rotation) : glm::normalize(new_rotation);''',
    '''        const auto eye_translation_rotation = (mono || qv_pose)
            ? glm::normalize(vqi_norm * current_hmd_rotation) : glm::normalize(new_rotation);''')
# The old exact-frame helper must never trust mutable scene-role ring stamps.
p = root / c
data = changes[p]
a = data.index('std::optional<OpenXR::PipelineState> OpenXR::capture_quadview_pose(uint32_t frame) {')
b = data.index('std::optional<OpenXR::PipelineState> OpenXR::capture_quadview_current_pose()', a)
changes[p] = data[:a] + '''std::optional<OpenXR::PipelineState> OpenXR::capture_quadview_pose(uint32_t frame) {
    auto pose=capture_quadview_current_pose();
    if (!pose || pose->frame_count!=frame) return {};
    return pose;
}

''' + data[b:]
# Drop the obsolete moving-latest comparison from the generated method entirely.
p = root / v
data = changes[p]
a = data.index('    /* B28 removed comparison with the moving latest locate.')
b = data.index('    } */\n', a) + len('    } */\n')
changes[p] = data[:a] + data[b:]
for path, data in changes.items():
    path.write_text(data, encoding='utf-8', newline='\n')
(root / 'src/mods/vr/TriViewLocatedPose.hpp').write_text((Path(__file__).parent / 'TriViewLocatedPose.hpp').read_text(encoding='utf-8'), encoding='utf-8')
print('B28 pose: coherent located head and eyes frozen for camera and submission')
