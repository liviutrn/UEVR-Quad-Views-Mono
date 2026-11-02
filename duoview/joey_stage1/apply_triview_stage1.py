#!/usr/bin/env python3
"""Tri-View Stage 1: rendering method ID 7 = Joey's Native Stereo + Native Fix + one centre periphery view.

Run AFTER the complete v207 patch chain (... apply_v207_auto_fov_after_load, verify_stage234).
Every edit is an exact anchor that must occur once. Modes 0-6 keep their code paths: every new branch is
gated by ID 7 (is_triview_active / is_triview_selected) or by Tri-View having requested a third view.
Design: research/2026-11-01-triview-stage1-decision.md.

  apply:   apply_triview_stage1.py BACKEND FRONTEND DUOVIEW_DIR EVIDENCE
  verify:  apply_triview_stage1.py --verify BACKEND EVIDENCE   (after the build: nothing changed)
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys

V207_EDITED = {
    "src/mods/vr/MonoRenderingPolicy.hpp", "src/mods/vr/CompatibilityPolicy.hpp",
    "src/mods/VR.hpp", "src/mods/VR.cpp",
    "src/mods/vr/OverlayComponent.hpp", "src/mods/vr/OverlayComponent.cpp",
    "src/mods/vr/FFakeStereoRenderingHook.cpp", "src/mods/vr/FFakeStereoRenderingHook.hpp",
    "src/mods/vr/runtimes/OpenXR.cpp", "src/mods/vr/runtimes/OpenXR.hpp",
    "src/mods/vr/D3D12Component.hpp", "src/mods/vr/D3D12Component.cpp", "tests/MonoRenderingTests.hpp",
    "tests/CadenceReplayTests.cpp",
}
V207_ADDED = {
    "src/mods/vr/DuoViewDelivery.hpp", "src/mods/vr/DuoViewGeometry.hpp", "src/mods/vr/DuoViewGaze.hpp",
    "src/mods/vr/DuoViewPSVR2Gaze.hpp", "src/mods/vr/DuoViewCropStability.hpp", "src/mods/vr/DuoViewFrame.hpp",
    "src/mods/vr/DuoViewConfig.hpp", "src/mods/vr/DuoViewState.hpp", "src/mods/vr/DuoViewD3D12.hpp",
    "src/mods/vr/DuoViewMonoCopyD3D12.hpp", "src/mods/vr/DuoViewShaderSource.hpp",
}
TRIVIEW_EDITED = {"src/mods/vr/RenderingMethodSetting.hpp"}
MODULE_FILES = ("TriViewGeometry.hpp", "TriViewD3D12.hpp", "TriViewCapture.hpp")
TRIVIEW_ADDED = {"src/mods/vr/" + n for n in MODULE_FILES} | {"src/mods/vr/TriViewShaderSource.hpp"}
FRONTEND_EDITED = {"UEVR/RenderingModeOptions.cs", "tests/RenderingModes/Program.cs"}
FRONTEND_GENERATED = {"UEVR/FilteredExecutables.json"}

LABEL = "Tri-View (Experimental)"

TRIVIEW_CAPTURE_IMPL = r'''// Tri-View ID7: automatic GPU capture, twice per session (after 600 and 3600 composited frames), so the
// physical placement of all three renders and the final image can be checked without headset questions.
// Writes TriView_Capture_N.zip next to the UEVR log: half-size BMPs of the main target's left half, the
// capture target, the periphery target and the XR image, plus report.txt with region statistics.
void D3D12Component::triview_take_capture(d3d12::CommandContext& commands, ID3D12Resource* destination,
                                          const uevr::triview::PacketLayout& frame, ID3D12Resource* periphery) try {
    auto& vr = VR::get();
    const auto taken = vr->m_triview_captures.load(std::memory_order_acquire);
    const uint64_t due = taken == 0 ? 600 : 3600;
    if (taken >= 2 || periphery == nullptr || destination == nullptr || commands.fence == nullptr ||
        vr->m_triview_composites.load(std::memory_order_acquire) + 1 < due) {
        return;
    }
    if (m_triview_capture == nullptr) { m_triview_capture = std::make_unique<uevr::triview::dx12::GpuCapture>(); }
    if (m_triview_capture->pending()) { return; }
    const auto& l = frame.layout;
    const auto dd = destination->GetDesc();
    const uint32_t eye = static_cast<uint32_t>(dd.Width / 2), tall = dd.Height;
    const uint32_t w = l.eye_width, h = l.eye_height;
    using Region = uevr::triview::capture::Region;
    const auto at = [](uint32_t size, float f) { return static_cast<uint32_t>(std::lround((std::max)(0.f, f) * size)); };
    std::vector<Region> xr_regions;
    for (uint32_t e = 0; e < 2; ++e) {
        const uint32_t base = e * eye;
        const std::string n = e == 0 ? "L_" : "R_";
        const auto& win = l.window[e];
        const uint32_t y0 = at(tall, win.v0 + (win.v1 - win.v0) * .25f), y1 = at(tall, win.v1 - (win.v1 - win.v0) * .25f);
        xr_regions.push_back({n + "fovea", base + at(eye, win.u0), at(tall, win.v0), base + at(eye, win.u1), at(tall, win.v1)});
        xr_regions.push_back({n + "outer_edge", base, 0, base + at(eye, .08f), tall});
        xr_regions.push_back({n + "top_edge", base, 0, base + eye, at(tall, .08f)});
        xr_regions.push_back({n + "seam_left_inside", base + at(eye, win.u0 + .02f), y0, base + at(eye, win.u0 + .05f), y1});
        xr_regions.push_back({n + "seam_left_outside", base + at(eye, win.u0 - .05f), y0, base + at(eye, win.u0 - .02f), y1});
        xr_regions.push_back({n + "seam_right_inside", base + at(eye, win.u1 - .05f), y0, base + at(eye, win.u1 - .02f), y1});
        xr_regions.push_back({n + "seam_right_outside", base + at(eye, win.u1 + .02f), y0, base + at(eye, win.u1 + .05f), y1});
    }
    const std::vector<uevr::triview::dx12::GpuCapture::Source> sources{
        {"main_left_half", m_game_tex.texture.Get(), w, h,
            {{"fovea", 0, 0, l.fovea_width, l.fovea_height}, {"right_of_fovea", l.fovea_width, 0, w, l.fovea_height},
             {"below_fovea", 0, l.fovea_height, w, h}}},
        {"capture", m_scene_capture_tex.texture.Get(), w, h,
            {{"fovea", 0, 0, l.fovea_width, l.fovea_height}, {"right_of_fovea", l.fovea_width, 0, w, l.fovea_height},
             {"below_fovea", 0, l.fovea_height, w, h}}},
        {"periphery", periphery, w, h,
            {{"image", 0, 0, l.periphery_width, l.periphery_height}, {"right_of_image", l.periphery_width, 0, w, h},
             {"below_image", 0, l.periphery_height, l.periphery_width, h}}},
        {"xr_both_eyes", destination, static_cast<uint32_t>(dd.Width), tall, xr_regions}};
    char text[2048];
    std::snprintf(text, sizeof(text),
        "Tri-View automatic capture %u (build: Tri-View S5)\n"
        "eye %ux%u, XR image %llux%u, fovea %ux%u, window L u %.4f..%.4f v %.4f..%.4f R u %.4f..%.4f v %.4f..%.4f, periphery %ux%u\n"
        "eye L tans l %.5f r %.5f t %.5f b %.5f | eye R tans l %.5f r %.5f t %.5f b %.5f\n"
        "periphery union tans l %.5f r %.5f t %.5f b %.5f\n"
        "map L ax %.6f bx %.6f ay %.6f by %.6f | map R ax %.6f bx %.6f ay %.6f by %.6f\n"
        "packet third=%d, periphery target status: %s, target builds %llu\n"
        "engine frames: third %llu, eyes only %llu, third skipped %llu; composites %llu, rejected %llu\n",
        taken + 1, w, h, static_cast<unsigned long long>(dd.Width), tall, l.fovea_width, l.fovea_height,
        l.window[0].u0, l.window[0].u1, l.window[0].v0, l.window[0].v1,
        l.window[1].u0, l.window[1].u1, l.window[1].v0, l.window[1].v1, l.periphery_width, l.periphery_height,
        l.eye[0].left, l.eye[0].right, l.eye[0].top, l.eye[0].bottom, l.eye[1].left, l.eye[1].right, l.eye[1].top, l.eye[1].bottom,
        l.periphery.left, l.periphery.right, l.periphery.top, l.periphery.bottom,
        uevr::triview::periphery_map(l, 0).ax, uevr::triview::periphery_map(l, 0).bx, uevr::triview::periphery_map(l, 0).ay,
        uevr::triview::periphery_map(l, 0).by, uevr::triview::periphery_map(l, 1).ax, uevr::triview::periphery_map(l, 1).bx,
        uevr::triview::periphery_map(l, 1).ay, uevr::triview::periphery_map(l, 1).by,
        frame.third ? 1 : 0, vr->m_triview_target_status.load(),
        static_cast<unsigned long long>(vr->m_triview_target_builds.load()),
        static_cast<unsigned long long>(vr->m_triview_third_renders.load()),
        static_cast<unsigned long long>(vr->m_triview_pair_only.load()),
        static_cast<unsigned long long>(vr->m_triview_third_skipped.load()),
        static_cast<unsigned long long>(vr->m_triview_composites.load()),
        static_cast<unsigned long long>(vr->m_triview_composite_rejects.load()));
    const auto path = Framework::get_persistent_dir() / ("TriView_Capture_" + std::to_string(taken + 1) + ".zip");
    if (m_triview_capture->record(g_framework->get_d3d12_hook()->get_device(), commands.cmd_list.Get(), sources,
            commands.fence.Get(), commands.fence_value + 1, path, text)) {
        vr->m_triview_captures.fetch_add(1, std::memory_order_acq_rel);
        SPDLOG_INFO("[TriView] Automatic capture {} queued: {}", taken + 1, path.string());
    } else {
        vr->m_triview_captures.fetch_add(1, std::memory_order_acq_rel);
        SPDLOG_WARN("[TriView] Automatic capture {} could not be recorded", taken + 1);
    }
} catch (...) {
    SPDLOG_WARNING_EVERY_N_SEC(10, "[TriView] Automatic capture failed with an exception");
}

'''


TRIVIEW_CTOR = r'''    // Tri-View ID7 (S4): test 1 capture showed the engine builds view index 2 with the GAME camera and the game's
    // ~92 deg FOV (its own pose, not the HMD; rect from adjust_view_rect), so the periphery swam against the foveas.
    // Write the centre camera and the union projection straight into this view's init options, the same way
    // Joey's SceneView-compatibility path writes eye views. The view is recognised by its rect (0,0,pw,ph),
    // which differs from the fovea rect by construction, in the main viewport family.
    if (vr->is_triview_active() && vr->triview_owns_view_index_two() && is_ue5 && !is_ue50_to_53) {
        const auto layout = vr->triview_layout();
        auto* const family = init_options->get_view_family();
        const auto rtm = g_hook->get_render_target_manager();
        FIntRect current{};
        std::memcpy(current.bounds, &init_options_ue5->view_rect, sizeof(current.bounds));
        const bool is_periphery = layout.has_value() && family != nullptr && rtm != nullptr &&
            family->get_render_target() == rtm->get_view_family_render_target() &&
            current.bounds[0] == 0 && current.bounds[1] == 0 &&
            current.bounds[2] == static_cast<int32_t>(layout->periphery_width) &&
            current.bounds[3] == static_cast<int32_t>(layout->periphery_height);
        double rotation[3]{}, position[3]{};
        if (is_periphery && vr->triview_centre_pose(rotation, position)) {
            const auto* before = reinterpret_cast<const double*>(&init_options_ue5->projection_matrix);
            const auto* origin_before = reinterpret_cast<const double*>(&init_options_ue5->view_origin);
            static uint64_t triview_ctor_logs{};
            if (triview_ctor_logs++ % 600 == 0) {
                SPDLOG_INFO("[TriView][ctor] view 2 as built by the engine: proj m00 {:.5f} m20 {:.5f} m11 {:.5f} m21 {:.5f} origin {:.1f} {:.1f} {:.1f}",
                    before[0], before[8], before[5], before[9], origin_before[0], origin_before[1], origin_before[2]);
                SPDLOG_INFO("[TriView][ctor] writing centre camera pitch {:.2f} yaw {:.2f} roll {:.2f} origin {:.1f} {:.1f} {:.1f}",
                    rotation[0], rotation[1], rotation[2], position[0], position[1], position[2]);
            }
            const auto conversion = glm::mat4{0, 0, 1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1};
            const glm::vec3 euler{static_cast<float>(rotation[0]), static_cast<float>(rotation[1]), static_cast<float>(rotation[2])};
            auto projection = vr->get_projection_matrix(VRRuntime::Eye::LEFT);
            uevr::triview::apply_periphery_projection(projection, *layout);
            init_options_ue5->view_rotation_matrix = conversion * utility::math::ue_inverse_rotation_matrix(euler);
            init_options_ue5->projection_matrix = projection;
            auto* const origin = reinterpret_cast<double*>(&init_options_ue5->view_origin);
            origin[0] = position[0]; origin[1] = position[1]; origin[2] = position[2];
            vr->m_triview_ctor_overrides.fetch_add(1, std::memory_order_relaxed);
        } else if (is_periphery) {
            SPDLOG_WARNING_EVERY_N_SEC(2, "[TriView][ctor] view 2 found but this frame's eye poses are missing; engine camera kept");
        }
    }

'''

TRIVIEW_TARGET_IMPL = r'''// ---- Tri-View ID7: the centre periphery's own render target ---------------------------------------
// Built exactly like Joey's STALKER 2 Native Fix capture target (create_scene_capture below): a Kismet
// render target, kept alive by a passive capture component on Joey's capture actor (no rooting, so it is
// collected with the world like his), validated through the same +0x110/+0x10/+0x50 chain on the render
// thread, and given the same display gamma as the viewport. Keyed to Joey's capture generation: a new
// world or a new capture generation means a new periphery target.
namespace {
float triview_target_display_gamma(const sdk::FRenderTarget*) {
    const auto rtm = g_hook != nullptr ? g_hook->get_render_target_manager() : nullptr;
    const auto viewport = rtm != nullptr ? rtm->get_viewport() : nullptr;
    if (viewport != nullptr) {
        const auto gamma = viewport->get_display_gamma();
        if (std::isfinite(gamma) && gamma > 0.0f) { return gamma; }
    }
    return 2.2f;
}

// Hooked FRenderTarget vtables, one per original vtable, never freed (a render-thread call may still be
// reading one while a target retires).
uintptr_t triview_hooked_vtable_for(uintptr_t original, size_t gamma_index) {
    static std::mutex mutex;
    static std::vector<std::pair<uintptr_t, std::array<uintptr_t, 100>*>> tables;
    std::scoped_lock lock{mutex};
    for (const auto& [from, table] : tables) {
        if (from == original || reinterpret_cast<uintptr_t>(table->data()) == original) {
            return reinterpret_cast<uintptr_t>(table->data());
        }
    }
    auto* table = new std::array<uintptr_t, 100>{};
    std::memcpy(table->data(), reinterpret_cast<const void*>(original), table->size() * sizeof(uintptr_t));
    (*table)[gamma_index] = reinterpret_cast<uintptr_t>(&triview_target_display_gamma);
    tables.emplace_back(original, table);
    return reinterpret_cast<uintptr_t>(table->data());
}
} // namespace

std::shared_ptr<const VRRenderTargetManager_Base::TriViewTargetSnapshot>
VRRenderTargetManager_Base::request_triview_target(uint32_t width, uint32_t height) {
    const auto generation = scene_capture_generation.load(std::memory_order_acquire);
    auto current = triview_target_snapshot.load(std::memory_order_acquire);
    if (current != nullptr && current->generation == generation && generation != 0 &&
        current->width == width && current->height == height) {
        return current;
    }
    if (generation == 0 || width == 0 || height == 0 || triview_target_requested.exchange(true, std::memory_order_acq_rel)) {
        return nullptr;
    }
    try {
        GameThreadWorker::get().enqueue([this, generation, width, height]() {
            triview_target_requested.store(false, std::memory_order_release);
            build_triview_target(generation, width, height);
        });
    } catch (...) {
        triview_target_requested.store(false, std::memory_order_release);
    }
    return nullptr;
}

void VRRenderTargetManager_Base::build_triview_target(uint64_t generation, uint32_t width, uint32_t height) try {
    auto* const vr = VR::get().get();
    if (generation != scene_capture_generation.load(std::memory_order_acquire)) { return; }
    if (const auto current = triview_target_snapshot.load(std::memory_order_acquire);
        current != nullptr && current->generation == generation && current->width == width && current->height == height) {
        return;
    }
    if (triview_target_attempts_generation != generation) {
        triview_target_attempts_generation = generation;
        triview_target_attempts = 0;
        triview_target_retry_after_ms = 0;
    }
    if (triview_target_building == generation || steady_clock_milliseconds() < triview_target_retry_after_ms) { return; }
    if (!stalker2_uses_validated_ue55_native_fix_capture_layout()) {
        vr->m_triview_target_status.store("unavailable: not the validated STALKER 2 UE5.5 capture layout");
        SPDLOG_WARNING_EVERY_N_SEC(5, "[TriView] Periphery target needs Joey's validated STALKER 2 UE5.5 capture layout");
        return;
    }
    if (triview_target_attempts >= 24) {
        vr->m_triview_target_status.store("gave up after 24 attempts (see log)");
        SPDLOG_ERROR_EVERY_N_SEC(10, "[TriView] Periphery target creation gave up after {} attempts", triview_target_attempts);
        return;
    }
    if (this->scene_capture_actor == nullptr || !this->scene_capture_actor.valid()) {
        vr->m_triview_target_status.store("waiting for Joey's capture actor");
        return;
    }
    sdk::UKismetRenderingLibrary* kismet{};
    if (const auto kismet_class = sdk::UKismetRenderingLibrary::static_class(); kismet_class != nullptr) {
        kismet = kismet_class->get_class_default_object<sdk::UKismetRenderingLibrary>();
    }
    static auto scene_capture_c = sdk::USceneCaptureComponent2D::static_class();
    auto* const engine = sdk::UGameEngine::get();
    auto* const world = engine != nullptr ? engine->get_world() : nullptr;
    if (kismet == nullptr || scene_capture_c == nullptr || world == nullptr) {
        vr->m_triview_target_status.store("waiting for world / Kismet");
        return;
    }
    ++triview_target_attempts;
    vr->m_triview_target_builds.fetch_add(1, std::memory_order_relaxed);
    triview_target_retry_after_ms = steady_clock_milliseconds() + 2000;
    const float clear_color[4]{0.0f, 0.0f, 0.0f, 1.0f};
    auto owner = std::make_shared<TriViewTargetOwner>();
    sdk::UTexture* texture_raw = kismet->create_render_target_2d(world, width, height, 2, clear_color, false);
    if (texture_raw == nullptr) {
        vr->m_triview_target_status.store("Kismet could not create the target (retrying)");
        SPDLOG_ERROR("[TriView] Kismet failed to create the {}x{} periphery target", width, height);
        return;
    }
    owner->texture = texture_raw;
    const auto plan = uevr::scene_capture::component_plan(false, false, is_ue_5_5_dx_backend());
    owner->component = static_cast<sdk::USceneCaptureComponent2D*>(
        this->scene_capture_actor->add_component_by_class(scene_capture_c, plan.deferred_add));
    if (owner->component == nullptr) {
        vr->m_triview_target_status.store("could not add the holder component (retrying)");
        SPDLOG_ERROR("[TriView] Failed to add the periphery holder component to Joey's capture actor");
        return;
    }
    // Passive holder, like Joey's: never captures, only keeps the texture referenced.
    owner->component->set_texture_target(owner->texture);
    owner->component->set_visibility(false);
    if (auto capture_every_frame = scene_capture_c->find_property(L"bCaptureEveryFrame"); capture_every_frame != nullptr) {
        *capture_every_frame->get_data<bool>(owner->component) = false;
    }
    if (auto capture_on_movement = scene_capture_c->find_property(L"bCaptureOnMovement"); capture_on_movement != nullptr) {
        *capture_on_movement->get_data<bool>(owner->component) = false;
    }
    if (plan.finish_after_configuration) {
        this->scene_capture_actor->finish_add_component(owner->component);
    }
    triview_target_building = generation;
    vr->m_triview_target_status.store("created, waiting for the engine to initialise it");
    SPDLOG_INFO("[TriView] Created periphery target {:x} ({}x{}) for capture generation {}",
        reinterpret_cast<uintptr_t>(texture_raw), width, height, generation);

    const auto release_building = [this, generation]() {
        try {
            GameThreadWorker::get().enqueue([this, generation]() {
                if (triview_target_building == generation) { triview_target_building = 0; }
            });
        } catch (...) {}
    };
    RenderThreadWorker::ConditionalJobFunc job = [this, owner, generation, width, height, release_building]() mutable -> bool {
        if (generation != scene_capture_generation.load(std::memory_order_acquire)) { return true; }
        if (!owner->texture.valid()) {
            SPDLOG_WARN("[TriView] Periphery texture disappeared before validation; will retry");
            release_building();
            return true;
        }
        const auto chain = validate_native_fix_texture_chain(owner->texture.get(), width, height,
            STALKER2_UE55_NATIVE_FIX_TEXTURE_LAYOUT);
        if (!chain) {
            SPDLOG_INFO_EVERY_N_SEC(2, "[TriView] Waiting for the periphery target's +0x110/+0x10 texture chain");
            return false;
        }
        const auto gamma_index = sdk::FRenderTarget::get_display_gamma_index();
        uintptr_t original{};
        if (!gamma_index.has_value() || *gamma_index >= 100 ||
            !safe_read_value(reinterpret_cast<uintptr_t>(chain->render_target), original) ||
            !is_readable_process_range(original, 100 * sizeof(uintptr_t))) {
            SPDLOG_ERROR("[TriView] Periphery target: FRenderTarget vtable / gamma slot unavailable; not publishing");
            release_building();
            return true;
        }
        *reinterpret_cast<uintptr_t*>(chain->render_target) = triview_hooked_vtable_for(original, *gamma_index);
        auto snapshot = std::make_shared<TriViewTargetSnapshot>();
        snapshot->render_target = chain->render_target;
        snapshot->native = chain->native_resource;
        snapshot->generation = generation;
        snapshot->width = width;
        snapshot->height = height;
        snapshot->owner = owner;
        triview_target_snapshot.store(std::move(snapshot), std::memory_order_release);
        VR::get()->m_triview_target_status.store("ready");
        release_building();   // a later size change in the same generation may build again
        SPDLOG_INFO("[TriView] Periphery target ready: FRenderTarget {:x}, D3D12 {:x}, {}x{}, generation {}",
            reinterpret_cast<uintptr_t>(chain->render_target), reinterpret_cast<uintptr_t>(chain->native_resource.Get()),
            width, height, generation);
        return true;
    };
    RenderThreadWorker::ConditionalJobTimeoutFunc on_timeout = [generation, release_building]() {
        SPDLOG_ERROR("[TriView] Periphery target generation {} did not initialise in time; will retry", generation);
        release_building();
    };
    RenderThreadWorker::get().enqueue_conditional(job, on_timeout, std::chrono::seconds(5));
} catch (const std::exception& e) {
    SPDLOG_ERROR("[TriView] Exception while creating the periphery target: {}", e.what());
} catch (...) {
    SPDLOG_ERROR("[TriView] Unknown exception while creating the periphery target");
}

'''


BACKEND = {
 # ---- rendering method ID 7 ------------------------------------------------------------------
 "src/mods/vr/MonoRenderingPolicy.hpp": [
  ('inline constexpr int32_t duoview_method_id = 6;\n',
   'inline constexpr int32_t duoview_method_id = 6;\n'
   '// Tri-View Stage 1: Native Stereo + Native Fix + one centre periphery view (not a Mono-family method).\n'
   'inline constexpr int32_t triview_method_id = 7;\n'),
  ('    Choice{duoview_method_id, "DuoView Mono (Eye Tracked - Experimental)"},\n};',
   '    Choice{duoview_method_id, "DuoView Mono (Eye Tracked - Experimental)"},\n'
   '    Choice{triview_method_id, "' + LABEL + '"},\n};'),
  ('non_dibr_choices {choices[0], choices[1], choices[2], choices[5], choices[6]};',
   'non_dibr_choices {choices[0], choices[1], choices[2], choices[5], choices[6], choices[7]};'),
 ],
 "src/mods/vr/RenderingMethodSetting.hpp": [
  ('    int32_t value() const { return m_selection.active(); }',
   '    // Tri-View (ID 7) runs every existing Native Stereo (ID 0) code path unchanged;\n'
   '    // Tri-View code checks the raw ID through selection().active().\n'
   '    int32_t value() const {\n'
   '        const auto active = m_selection.active();\n'
   '        return active == uevr::mono::triview_method_id ? 0 : active;\n'
   '    }'),
 ],
 "tests/MonoRenderingTests.hpp": [
  ('    for (int id = 0; id != 7; ++id) {', '    for (int id = 0; id != 8; ++id) {'),
  ('(id < 3 || id == 5 || id == 6),', '(id < 3 || id == 5 || id == 6 || id == 7),'),
  ('    expect(!m::available(-1) && !m::available(7), "unsupported IDs are identified, never clamped into Mono");',
   '    expect(!m::available(-1) && !m::available(8), "unsupported IDs are identified, never clamped into Mono");\n'
   '    expect(m::triview_method_id == 7 && !m::is_mono_family(m::triview_method_id),\n'
   '        "Tri-View keeps serialized ID 7 and never enters the Mono lifecycle");'),
 ],
 # ---- VR state, settings and mode predicates ---------------------------------------------------
 "src/mods/VR.hpp": [
  ('#include "vr/DuoViewState.hpp"\n#include "vr/DuoViewPSVR2Gaze.hpp"',
   '#include "vr/DuoViewState.hpp"\n#include "vr/DuoViewPSVR2Gaze.hpp"\n#include "vr/TriViewGeometry.hpp"'),
  ('        if (is_duoview_renderer_active()) { return true; }\n\n        return m_native_stereo_fix->value() &&',
   '        if (is_duoview_renderer_active()) { return true; }\n'
   '        if (is_triview_active()) { return true; } // Tri-View ID7 forces Native Fix on\n\n'
   '        return m_native_stereo_fix->value() &&'),
  ('        return m_native_stereo_fix_texture_array_submit->value() &&\n',
   '        if (is_triview_selected()) { return false; } // Tri-View composes its own XR image\n'
   '        return m_native_stereo_fix_texture_array_submit->value() &&\n'),
  ('    bool is_duoview_renderer_active() const;\n',
   '    bool is_duoview_renderer_active() const;\n'
   '    // Tri-View Stage 1 (ID 7): Native Stereo + Native Fix + one centre periphery view.\n'
   '    bool is_triview_selected() const {\n'
   '        return m_rendering_method->selection().active() == uevr::mono::triview_method_id;\n'
   '    }\n'
   '    bool is_triview_active() const;\n'
   '    bool triview_third_view_enabled() const { return m_triview_third_view->value(); }\n'
   '    unsigned triview_debug_mode() const { return m_triview_border->value() ? 1u : 0u; }\n'
   '    // Periphery render-target status for the menu and the capture report (string literals only).\n'
   '    std::atomic<const char*> m_triview_target_status{"not requested"};\n'
   '    std::atomic<uint64_t> m_triview_target_builds{}, m_triview_third_skipped{};\n'
   '    std::atomic<uint32_t> m_triview_captures{};\n'
   '    std::atomic<uint64_t> m_triview_ctor_overrides{};\n'
   '    // Entering Tri-View from another method: restart Native Fix once (fresh capture + pair learning).\n'
   '    bool triview_fresh_start_due();\n'
   '    // The fovea window each eye was really rendered with (projection hook), carried by the packet.\n'
   '    void triview_note_applied_window(int eye, const uevr::triview::Window& window) {\n'
   '        std::scoped_lock lock{m_triview_layout_mutex};\n'
   '        m_triview_applied_window[eye != 0 ? 1 : 0] = window;\n'
   '    }\n'
   '    std::optional<uevr::triview::Window> triview_applied_window(int eye) {\n'
   '        std::scoped_lock lock{m_triview_layout_mutex};\n'
   '        return m_triview_applied_window[eye != 0 ? 1 : 0];\n'
   '    }\n'
   '    std::optional<uevr::triview::Layout> triview_layout();\n'
   '    void triview_note_eye_pose(int32_t index, const double* rotation, const double* position);\n'
   '    bool triview_centre_pose(double* rotation, double* position) const;\n'
   '    void note_triview_views_demanded() { m_triview_owns_index_two.store(true, std::memory_order_release); }\n'
   '    void clear_triview_views_demanded() { m_triview_owns_index_two.store(false, std::memory_order_release); }\n'
   '    // View index 2 is ours while Tri-View is active, and for the frames still carrying a third view\n'
   '    // that Tri-View demanded. The latch is dropped by the first GetDesiredNumberOfViews call that no\n'
   '    // longer demands it, and is ignored once another rendering method is selected.\n'
   '    bool triview_owns_view_index_two() const {\n'
   '        return is_triview_active() ||\n'
   '            (is_triview_selected() && m_triview_owns_index_two.load(std::memory_order_acquire));\n'
   '    }\n'
   '    std::atomic<uint64_t> m_triview_third_renders{}, m_triview_pair_only{};\n'
   '    std::atomic<uint64_t> m_triview_composites{}, m_triview_composite_rejects{};\n'),
  ('    std::once_flag m_duoview_settings_once;\n',
   '    std::once_flag m_duoview_settings_once;\n'
   '    const ModToggle::Ptr m_triview_third_view{ModToggle::create(generate_name("TriViewThirdView"), true)};\n'
   '    const ModSlider::Ptr m_triview_periphery_scale{ModSlider::create(generate_name("TriViewPeripheryScale"), .25f, 1.f, .5f)};\n'
   '    const ModToggle::Ptr m_triview_eye_tracked{ModToggle::create(generate_name("TriViewEyeTracked"), true)};\n'
   '    const ModSlider::Ptr m_triview_fovea_size{ModSlider::create(generate_name("TriViewFoveaSize"), .3f, .8f, .5f)};\n'
   '    // Tri-View S3: one layout per engine frame (gaze sampled once), shared by every hook of that frame.\n'
   '    std::mutex m_triview_layout_mutex{};\n'
   '    uint64_t m_triview_layout_frame{UINT64_MAX};\n'
   '    std::optional<uevr::triview::Layout> m_triview_layout_cached{};\n'
   '    uevr::duoview::CropStability m_triview_stability{};\n'
   '    std::atomic<bool> m_triview_gaze_live{false};\n'
   '    uint64_t m_triview_fresh_generation{UINT64_MAX}; // game thread\n'
   '    std::array<std::optional<uevr::triview::Window>, 2> m_triview_applied_window{};\n'
   '    const ModToggle::Ptr m_triview_border{ModToggle::create(generate_name("TriViewDebugBorder"), false)};\n'

   '    std::atomic<bool> m_triview_owns_index_two{false};\n'
   '    std::array<std::array<double, 6>, 2> m_triview_eye_pose{}; // game thread only\n'
   '    std::array<bool, 2> m_triview_eye_seen{};\n'),
  ('            *m_duo_sharp_periphery,',
   '            *m_duo_sharp_periphery,\n'
   '            *m_triview_third_view, *m_triview_periphery_scale, *m_triview_border, *m_triview_eye_tracked, *m_triview_fovea_size,'),
 ],
 "src/mods/VR.cpp": [
  ('bool VR::should_force_native_stereo_fix_same_pass() const {\n    if (is_duoview_renderer_active()) {',
   'bool VR::should_force_native_stereo_fix_same_pass() const {\n'
   '    if (is_triview_active()) {\n'
   '        // Tri-View forces Native Fix on: keep Joey\'s validated STALKER 2 same-pass layout.\n'
   '        return stalker2_native_fix_requires_same_pass_cached();\n'
   '    }\n'
   '    if (is_duoview_renderer_active()) {'),
  ('    if (is_duoview_renderer_active()) { return false; }\n    if (!m_stalker2_native_pair_experiment->value()',
   '    if (is_duoview_renderer_active()) { return false; }\n'
   '    if (is_triview_active()) { return false; } // Tri-View composes from the generic Native Fix packet\n'
   '    if (!m_stalker2_native_pair_experiment->value()'),
  ('        if (rendering_method_changed && !is_mono_transition_pending() && get_runtime() != nullptr) {',
   '        if (is_triview_selected()) {\n'
   '            if (ImGui::TreeNode("Tri-View - settings and status")) {\n'
   '                ImGui::TextWrapped(is_triview_active()\n'
   '                    ? "Tri-View active: both eyes render their centre half (Native Fix), plus one low-res full-view periphery from the centre camera."\n'
   '                    : "Tri-View inactive (needs STALKER 2, D3D12, OpenXR, no AFR / 2D screen): rendering plain Native Stereo.");\n'
   '                m_triview_third_view->draw("Third view (periphery). OFF = cropped stereo windows only");\n'
   '                m_triview_periphery_scale->draw("Periphery resolution scale");\n'
   '                m_triview_eye_tracked->draw("Eye-tracked fovea (PSVR2; uses DuoView\'s gaze offset / smoothing settings)");\n'
   '                m_triview_fovea_size->draw("Fovea size (fraction of each eye)");\n'
   '                ImGui::Text("Gaze: %s", !m_triview_eye_tracked->value() ? "off (fixed centre)" :\n'
   '                    m_triview_gaze_live.load() ? "tracking" : "no PSVR2 gaze (centre or last position)");\n'
   '                m_triview_border->draw("Fovea border highlight");\n'
   '                ImGui::Text("Periphery target: %s (built %llu times)", m_triview_target_status.load(),\n'
   '                    static_cast<unsigned long long>(m_triview_target_builds.load()));\n'
   '                if (const auto layout = triview_layout()) {\n'
   '                    ImGui::Text("Fovea %ux%u per eye, periphery %ux%u", layout->fovea_width, layout->fovea_height,\n'
   '                        layout->periphery_width, layout->periphery_height);\n'
   '                }\n'
   '                ImGui::Text("Engine frames: %llu with third view, %llu eyes only (%llu third views skipped)",\n'
   '                    static_cast<unsigned long long>(m_triview_third_renders.load()),\n'
   '                    static_cast<unsigned long long>(m_triview_pair_only.load()),\n'
   '                    static_cast<unsigned long long>(m_triview_third_skipped.load()));\n'
   '                ImGui::Text("Automatic captures written: %u (TriView_Capture_N.zip next to the UEVR log)", m_triview_captures.load());\n'
   '                ImGui::Text("Periphery camera written by Tri-View: %llu views", static_cast<unsigned long long>(m_triview_ctor_overrides.load()));\n'
   '                ImGui::Text("Composited frames: %llu, rejected (Joey copy shown): %llu",\n'
   '                    static_cast<unsigned long long>(m_triview_composites.load()),\n'
   '                    static_cast<unsigned long long>(m_triview_composite_rejects.load()));\n'
   '                const auto q0 = glm::normalize(glm::quat{get_eye_transform(0)});\n'
   '                const auto q1 = glm::normalize(glm::quat{get_eye_transform(1)});\n'
   '                const float cant = glm::degrees(2.f * std::acos(std::clamp(std::abs(glm::dot(q0, q1)), 0.f, 1.f)));\n'
   '                ImGui::Text("Measured eye cant: %.2f deg (Stage 1 assumes parallel eyes)", cant);\n'
   '                ImGui::TreePop();\n'
   '            }\n'
   '        }\n'
   '        if (rendering_method_changed && !is_mono_transition_pending() && get_runtime() != nullptr) {'),
 ],
 # ---- packet carries the per-frame layout ------------------------------------------------------
 "src/mods/vr/FFakeStereoRenderingHook.hpp": [
  ('#include "Stalker2NativePolicy.hpp"\n#include "DuoViewState.hpp"',
   '#include "Stalker2NativePolicy.hpp"\n#include "DuoViewState.hpp"\n#include "TriViewGeometry.hpp"'),
  ('        bool duoview_pose_valid{};',
   '        bool duoview_pose_valid{};\n'
   '        uevr::triview::PacketLayout triview{}; // Tri-View ID7: layout + whether view 2 was rendered\n'
   '        // Tri-View ID7: the periphery target view 2 was rendered into (keeps its D3D12 resource alive).\n'
   '        std::shared_ptr<const VRRenderTargetManager_Base::TriViewTargetSnapshot> triview_target{};'),
  ('    std::shared_ptr<const SceneCaptureTargetSnapshot> get_scene_capture_target_snapshot() const {\n',
   '    // Tri-View ID7: the centre periphery gets its own render target, of the same kind as the Native Fix\n'
   '    // capture (STALKER 2.10 / UE 5.5.4 puts every singleton render at (0,0) of its target). A passive\n'
   '    // capture component on Joey\'s capture actor keeps the texture alive, so it lives and dies with\n'
   '    // Joey\'s capture generation and world.\n'
   '    struct TriViewTargetOwner {\n'
   '        sdk::UObjectReference<sdk::UTexture> texture{nullptr};\n'
   '        sdk::UObjectReference<sdk::USceneCaptureComponent2D> component{nullptr};\n'
   '    };\n'
   '    struct TriViewTargetSnapshot {\n'
   '        sdk::FRenderTarget* render_target{};\n'
   '        Microsoft::WRL::ComPtr<ID3D12Resource> native{};\n'
   '        uint64_t generation{};          // Joey\'s scene-capture generation it belongs to\n'
   '        uint32_t width{}, height{};\n'
   '        std::shared_ptr<TriViewTargetOwner> owner{};\n'
   '    };\n'
   '    std::shared_ptr<const TriViewTargetSnapshot> get_triview_target() const {\n'
   '        return triview_target_snapshot.load(std::memory_order_acquire);\n'
   '    }\n'
   '    // Game thread. Returns the published target when it matches Joey\'s current capture generation and\n'
   '    // the size; otherwise schedules its creation (game-thread worker) and returns nullptr.\n'
   '    std::shared_ptr<const TriViewTargetSnapshot> request_triview_target(uint32_t width, uint32_t height);\n'
   '    std::shared_ptr<const SceneCaptureTargetSnapshot> get_scene_capture_target_snapshot() const {\n'),
  ('    std::atomic<std::shared_ptr<const SceneCaptureTargetSnapshot>> scene_capture_target_snapshot{};\n',
   '    std::atomic<std::shared_ptr<const SceneCaptureTargetSnapshot>> scene_capture_target_snapshot{};\n'
   '    void build_triview_target(uint64_t generation, uint32_t width, uint32_t height);\n'
   '    std::atomic<std::shared_ptr<const TriViewTargetSnapshot>> triview_target_snapshot{};\n'
   '    std::atomic_bool triview_target_requested{};\n'
   '    uint64_t triview_target_building{};          // generation being validated (game thread)\n'
   '    uint64_t triview_target_retry_after_ms{};    // game thread\n'
   '    uint32_t triview_target_attempts{};          // game thread, capped per capture generation\n'
   '    uint64_t triview_target_attempts_generation{}; // game thread\n'),
 ],
 # ---- engine side: view count, index-2 hooks, third render -------------------------------------
 "src/mods/vr/FFakeStereoRenderingHook.cpp": [
  # GetDesiredNumberOfViews: third engine view (only after all Native Fix readiness checks).
  ('        SPDLOG_INFO_EVERY_N_SEC(2, "[Avowed][NativeStereoFix] Returning two views for native stereo fix");\n'
   '    }\n\n    return 2;\n}',
   '        SPDLOG_INFO_EVERY_N_SEC(2, "[Avowed][NativeStereoFix] Returning two views for native stereo fix");\n'
   '    }\n\n'
   '    if (vr->is_triview_active() && vr->is_hmd_active() && vr->is_native_stereo_fix_enabled() &&\n'
   '        vr->triview_third_view_enabled() && g_hook->m_has_double_precision && vr->triview_layout().has_value()) {\n'
   '        // Tri-View: view 2 = centre periphery, built by the engine exactly like the two eyes, once its\n'
   '        // own render target exists (created on demand, same lifetime as Joey\'s capture target).\n'
   '        auto* const triview_rtm = g_hook->get_render_target_manager();\n'
   '        if (triview_rtm != nullptr && vr->triview_fresh_start_due()) {\n'
   '            // Test 1: switching DuoView ID6 -> Tri-View gave a black picture; the Native Stereo + Fix detour\n'
   '            // (fresh capture generation, pair re-learned) fixed it. Do that detour automatically, once.\n'
   '            SPDLOG_INFO("[TriView] Entering Tri-View: restarting Native Fix with a fresh capture generation");\n'
   '            triview_rtm->destroy_scene_capture();\n'
   '            return 2;\n'
   '        }\n'
   '        if (triview_rtm != nullptr && triview_rtm->request_triview_target(\n'
   '                static_cast<uint32_t>(vr->get_hmd_width()), static_cast<uint32_t>(vr->get_hmd_height())) != nullptr) {\n'
   '            vr->note_triview_views_demanded();\n'
   '            return 3;\n'
   '        }\n'
   '        SPDLOG_INFO_EVERY_N_SEC(2, "[TriView] Waiting for the periphery render target ({}); eyes only", vr->m_triview_target_status.load());\n'
   '    }\n\n'
   '    if (!vr->is_triview_active()) { vr->clear_triview_views_demanded(); }\n\n'
   '    return 2;\n}'),
  # adjust_view_rect: index 2 before the legacy one-based heuristic.
  ('    if (!g_framework->is_game_data_intialized()) {\n        return;\n    }\n\n'
   '    static bool index_starts_from_one = true;\n    const bool medium_one_based_eye_pass = medium_is_current_game();',
   '    if (!g_framework->is_game_data_intialized()) {\n        return;\n    }\n\n'
   '    // Tri-View: index 2 is the centre periphery, rendered into its own target at (0,0) (UE 5.5.4\n'
   '    // ignores the rect position of a singleton render anyway: Build 52 GPU capture).\n'
   '    // Handled before the legacy "index 2 means one-based eyes" heuristic below.\n'
   '    if (index == 2 && VR::get()->triview_owns_view_index_two()) {\n'
   '        const auto layout = VR::get()->triview_layout();\n'
   '        *x = 0;\n'
   '        *y = 0;\n'
   '        *w = layout ? layout->periphery_width : VR::get()->get_hmd_width() / 2;\n'
   '        *h = layout ? layout->periphery_height : VR::get()->get_hmd_height() / 2;\n'
   '        return;\n'
   '    }\n\n'
   '    static bool index_starts_from_one = true;\n    const bool medium_one_based_eye_pass = medium_is_current_game();'),
  # adjust_view_rect: eyes 0/1 = fovea at (0,0) of their Native Fix targets.
  ('    if (VR::get()->is_duoview_renderer_active() && g_hook->m_has_double_precision &&\n        (index == 0 || index == 1)) {',
   '    if (VR::get()->is_triview_active() && (index == 0 || index == 1)) {\n'
   '        if (const auto layout = VR::get()->triview_layout()) {\n'
   '            *x = 0;\n'
   '            *y = 0;\n'
   '            *w = layout->fovea_width;\n'
   '            *h = layout->fovea_height;\n'
   '            return;\n'
   '        }\n'
   '    }\n'
   '    if (VR::get()->is_duoview_renderer_active() && g_hook->m_has_double_precision &&\n        (index == 0 || index == 1)) {'),
  # calculate_stereo_view_offset: index 2 = centre camera, before the legacy statics and Lua callbacks.
  ('    auto vr = VR::get();\n    if (vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 1) {',
   '    auto vr = VR::get();\n'
   '    if (view_index == 2 && vr->triview_owns_view_index_two()) {\n'
   '        // Tri-View centre camera: midpoint of the two eye poses computed above for this frame,\n'
   '        // left-eye rotation. Never reaches the legacy index-2 heuristics below.\n'
   '        double rotation[3]{}, position[3]{};\n'
   '        if (g_hook->m_has_double_precision && vr->triview_centre_pose(rotation, position)) {\n'
   '            auto* rot = reinterpret_cast<Rotator<double>*>(view_rotation);\n'
   '            auto* pos = reinterpret_cast<Vector3d*>(view_location);\n'
   '            rot->pitch = rotation[0]; rot->yaw = rotation[1]; rot->roll = rotation[2];\n'
   '            pos->x = position[0]; pos->y = position[1]; pos->z = position[2];\n'
   '        }\n'
   '        return;\n'
   '    }\n'
   '    if (vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 1) {'),
  # calculate_stereo_view_offset: remember the final eye poses (after Joey's math and Lua mods).
  ('        if (vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 0) {',
   '        if (vr->is_triview_active() && has_double_precision && (view_index == 0 || view_index == 1)) {\n'
   '            const double rotation[3]{rot_d->pitch, rot_d->yaw, rot_d->roll};\n'
   '            const double position[3]{view_d->x, view_d->y, view_d->z};\n'
   '            vr->triview_note_eye_pose(view_index, rotation, position);\n'
   '        }\n'
   '        if (vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 0) {'),
  # projection: index 2 = union frustum, before the legacy statics.
  ('    static bool index_starts_from_one = true;\n    static bool index_was_ever_two = false;\n\n'
   '    const bool medium_one_based_projection_pass = medium_is_current_game();',
   '    // Tri-View: index 2 = centre periphery, the left-eye projection widened to the union of\n'
   '    // both eye frusta. Handled before the legacy index-2 heuristics below.\n'
   '    if (view_index == 2 && out != nullptr && vr->triview_owns_view_index_two()) {\n'
   '        if (g_hook->m_has_double_precision) {\n'
   '            auto& matrix = *(Matrix4x4d*)out;\n'
   '            matrix = vr->get_projection_matrix(VRRuntime::Eye::LEFT);\n'
   '            if (const auto layout = vr->triview_layout()) {\n'
   '                uevr::triview::apply_periphery_projection(matrix, *layout);\n'
   '            }\n'
   '        } else {\n'
   '            *out = vr->get_projection_matrix(VRRuntime::Eye::LEFT);\n'
   '        }\n'
   '        return out;\n'
   '    }\n\n'
   '    static bool index_starts_from_one = true;\n    static bool index_was_ever_two = false;\n\n'
   '    const bool medium_one_based_projection_pass = medium_is_current_game();'),
  # projection: eyes 0/1 cropped to the fixed centre fovea window.
  ('            double_matrix = fmat;\n        }\n        if (duo_fovea || duo_full) {',
   '            double_matrix = fmat;\n        }\n'
   '        if (vr->is_triview_active() && g_hook->m_has_double_precision && (view_index == 0 || view_index == 1)) {\n'
   '            if (const auto layout = vr->triview_layout()) {\n'
   '                uevr::triview::apply_fovea_projection(double_matrix, *layout, static_cast<int>(true_index));\n'
   '                vr->triview_note_applied_window(static_cast<int>(true_index), layout->window[true_index != 0 ? 1 : 0]);\n'
   '            }\n'
   '        }\n'
   '        if (duo_fovea || duo_full) {'),
  # FSceneView constructor: view 2 gets the centre camera + union projection written into its init options.
  ('    if (vr->is_splitscreen_compatibility_enabled() ||\n        vr->is_sceneview_compatibility_enabled() ||\n        dune_manual_custom_present_pose) {\n        int32_t w = vr->get_hmd_width();',
   TRIVIEW_CTOR + '    if (vr->is_splitscreen_compatibility_enabled() ||\n        vr->is_sceneview_compatibility_enabled() ||\n        dune_manual_custom_present_pose) {\n        int32_t w = vr->get_hmd_width();'),
  # BeginRenderingViewFamily: hide view 2 from every existing Native Fix path.
  ('    if (view_family == nullptr) {\n        call_original();\n        return;\n    }\n\n'
   '    using SceneViewsArrayPtr = decltype(view_family->get_views());',
   '    if (view_family == nullptr) {\n        call_original();\n        return;\n    }\n\n'
   '    // Tri-View ID7: the engine built a third (centre periphery) view. Hide it so Joey\'s proven\n'
   '    // pair logic below sees exactly its two eyes. It is rendered once after the validated\n'
   '    // secondary render; the engine\'s view count is restored on every exit.\n'
   '    sdk::FSceneView* triview_third_view{};\n'
   '    sdk::FSceneViewFamily* triview_family{};\n'
   '    bool triview_rendered{};\n'
   '    std::shared_ptr<const VRRenderTargetManager_Base::TriViewTargetSnapshot> triview_used_target{};\n'
   '    utility::ScopeGuard triview_restore_count{[&]() {\n'
   '        if (triview_family != nullptr) { triview_family->get_views()->count = 3; }\n'
   '    }};\n'
   '    if (native_stereo_fix_enabled) {\n'
   '        const auto triview_main_target = rtm != nullptr ? rtm->get_view_family_render_target() : nullptr;\n'
   '        for (const auto family : view_families) {\n'
   '            if (family == nullptr || triview_main_target == nullptr ||\n'
   '                family->get_render_target() != triview_main_target) { continue; }\n'
   '            auto* const family_views = family->get_views();\n'
   '            if (family_views == nullptr ||\n'
   '                !is_readable_process_range(reinterpret_cast<uintptr_t>(family_views), sizeof(*family_views)) ||\n'
   '                family_views->count != 3) { continue; }\n'
   '            // Fail closed: a Native Fix main family with three views is ALWAYS cut back to Joey\'s two\n'
   '            // eyes (count restored on exit), even when the third view cannot be identified or Tri-View\n'
   '            // was just switched off; then the third view is simply not rendered.\n'
   '            if (family_views->capacity >= 3 && family_views->data != nullptr &&\n'
   '                is_readable_process_range(reinterpret_cast<uintptr_t>(family_views->data), sizeof(void*) * 3)) {\n'
   '                auto* const third = family_views->data[2];\n'
   '                if (third != nullptr && third != family_views->data[0] && third != family_views->data[1]) {\n'
   '                    triview_third_view = third;\n'
   '                }\n'
   '            }\n'
   '            triview_family = family;\n'
   '            family_views->count = 2;\n'
   '            break;\n'
   '        }\n'
   '    }\n\n'
   '    using SceneViewsArrayPtr = decltype(view_family->get_views());'),
  # Third render: exactly like Joey's secondary (frame-count decrement, singleton family), into its OWN target.
  ('            render_secondary_view();\n        }\n    }\n    stalker_secondary_frame = stalker_family_frame();',
   '            render_secondary_view();\n        }\n    }\n'
   '    if (triview_third_view != nullptr && triview_family == view_family && vr->is_triview_active()) {\n'
   '        // Tri-View: render the hidden centre view exactly like Joey\'s secondary above (frame-count\n'
   '        // decrement, singleton family), but into the periphery\'s own render target at (0,0).\n'
   '        // STALKER 2.10 (UE 5.5.4) puts a singleton render at its target\'s origin whatever the view rect\n'
   '        // says (Build 52 GPU capture), so sharing Joey\'s main target would paint over the left fovea.\n'
   '        // Its own target also means no engine flag writes: clearing that target is harmless.\n'
   '        // Joey\'s restore guard puts views/count/target back afterwards.\n'
   '        static bool triview_skip_decrement{}, triview_disabled{}, triview_last_rendered{};\n'
   '        static uint32_t triview_last_frame{};\n'
   '        static uint64_t triview_statics_generation{};\n'
   '        if (rtm != nullptr && triview_statics_generation != rtm->get_scene_capture_generation()) {\n'
   '            triview_statics_generation = rtm->get_scene_capture_generation();\n'
   '            triview_skip_decrement = triview_disabled = triview_last_rendered = false;\n'
   '        }\n'
   '        const size_t frame_offset = SceneViewExtensionAnalyzer::frame_count_offset;\n'
   '        auto* const family_bytes = reinterpret_cast<uint8_t*>(view_family);\n'
   '        uint32_t frame_before{};\n'
   '        const bool frame_readable = frame_offset >= 0x10 && frame_offset < 0x1000 &&\n'
   '            is_readable_process_range(reinterpret_cast<uintptr_t>(family_bytes) + frame_offset, sizeof(frame_before));\n'
   '        if (frame_readable) {\n'
   '            std::memcpy(&frame_before, family_bytes + frame_offset, sizeof(frame_before));\n'
   '            // The eyes\' frame number must advance every frame. If it stalls after a frame with a third\n'
   '            // render, drop the extra decrement (one repeated frame number, once); if it still stalls, stop.\n'
   '            if (triview_last_rendered && frame_before == triview_last_frame) {\n'
   '                if (!triview_skip_decrement) {\n'
   '                    triview_skip_decrement = true;\n'
   '                    SPDLOG_INFO("[TriView] Frame number stalled after a third render; no decrement from now on");\n'
   '                } else if (!triview_disabled) {\n'
   '                    triview_disabled = true;\n'
   '                    SPDLOG_ERROR("[TriView] Frame number still stalls without decrement; third view disabled");\n'
   '                }\n'
   '            }\n'
   '            triview_last_frame = frame_before;\n'
   '            triview_last_rendered = false;\n'
   '        }\n'
   '        const auto layout = vr->triview_layout();\n'
   '        auto target = rtm != nullptr ? rtm->get_triview_target() : nullptr;\n'
   '        const char* skip = nullptr;\n'
   '        if (triview_disabled) { skip = "disabled after frame-number stall"; }\n'
   '        else if (!layout) { skip = "no layout"; }\n'
   '        else if (target == nullptr || target->render_target == nullptr || target->native == nullptr) { skip = "no periphery target"; }\n'
   '        else if (target->generation != rtm->get_scene_capture_generation()) { skip = "periphery target belongs to an old capture generation"; }\n'
   '        else if (target->width < layout->periphery_width || target->height < layout->periphery_height) { skip = "periphery target too small"; }\n'
   '        else if (target->owner == nullptr || !target->owner->texture.valid()) { skip = "periphery texture no longer exists"; }\n'
   '        if (skip != nullptr) {\n'
   '            vr->m_triview_third_skipped.fetch_add(1, std::memory_order_relaxed);\n'
   '            SPDLOG_WARNING_EVERY_N_SEC(2, "[TriView] Third view skipped: {}", skip);\n'
   '        } else {\n'
   '            SPDLOG_INFO_ONCE("[TriView] Rendering the centre periphery into its own target {:x} ({}x{}, rect {}x{} at 0,0), capture generation {}, FrameNumber +0x{:x}={}",\n'
   '                reinterpret_cast<uintptr_t>(target->render_target), target->width, target->height,\n'
   '                layout->periphery_width, layout->periphery_height, target->generation, frame_offset, frame_before);\n'
   '            view_family->set_render_target(target->render_target);\n'
   '            views.data[0] = triview_third_view;\n'
   '            views.count = 1;\n'
   '            if (auto* scene = reinterpret_cast<sdk::FScene*>(view_family_scene); scene != nullptr && !triview_skip_decrement) {\n'
   '                scene->decrement_frame_count();\n'
   '            }\n'
   '            render_secondary_view();\n'
   '            triview_rendered = true;\n'
   '            triview_used_target = std::move(target);\n'
   '            triview_last_rendered = true;\n'
   '        }\n'
   '    }\n'
   '    stalker_secondary_frame = stalker_family_frame();'),
  ('        if (!duo_packet_frame) {\n            packet->engine_frame = g_frame_count;\n'
   '            packet->render_frame = vr->m_render_frame_count;\n        }\n',
   '        if (!duo_packet_frame) {\n            packet->engine_frame = g_frame_count;\n'
   '            packet->render_frame = vr->m_render_frame_count;\n        }\n'
   '        if (vr->is_triview_active()) {\n'
   '            if (const auto layout = vr->triview_layout()) {\n'
   '                auto rendered_layout = *layout;\n'
   '                for (int eye = 0; eye < 2; ++eye) {\n'
   '                    if (const auto applied = vr->triview_applied_window(eye)) { rendered_layout.window[eye] = *applied; }\n'
   '                }\n'
   '                packet->triview = uevr::triview::PacketLayout{rendered_layout, true, triview_rendered};\n'
   '                packet->triview_target = triview_rendered ? triview_used_target : nullptr;\n'
   '                (triview_rendered ? vr->m_triview_third_renders : vr->m_triview_pair_only)\n'
   '                    .fetch_add(1, std::memory_order_relaxed);\n'
   '            }\n'
   '        }\n'),
  ('bool VRRenderTargetManager_Base::create_ue58_ui_texture() {',
   TRIVIEW_TARGET_IMPL + 'bool VRRenderTargetManager_Base::create_ue58_ui_texture() {'),
 ],
 # ---- D3D12: compose instead of Joey's copy, only while ID 7 is active ----------------------------
 # v207 source-contract test counts D3D12 consume sites (4 -> 5: the Tri-View compositor is the new one).
 "tests/CadenceReplayTests.cpp": [
  ('copies == (std::string(backend) == "D3D11" ? 2 : 4) &&',
   'copies == (std::string(backend) == "D3D11" ? 2 : 5) &&'),
 ],
 "src/mods/vr/D3D12Component.hpp": [
  ('#include "d3d12/TextureContext.hpp"\n#include "DuoViewD3D12.hpp"',
   '#include "d3d12/TextureContext.hpp"\n#include "DuoViewD3D12.hpp"\n#include "TriViewD3D12.hpp"'),
  ('        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;',
   '        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;\n'
   '        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::triview::dx12::Compositor>> triview_compositors;'),
  ('    uint32_t m_scene_capture_height{};\n',
   '    uint32_t m_scene_capture_height{};\n'
   '    uevr::triview::PacketLayout m_triview_last{}; // Tri-View: layout of the last composed packet\n'
   '    Microsoft::WRL::ComPtr<ID3D12Resource> m_triview_last_periphery{}; // its periphery target (if rendered)\n'
   '    std::unique_ptr<uevr::triview::dx12::GpuCapture> m_triview_capture{}; // automatic one-shot captures\n'
   '    void triview_take_capture(d3d12::CommandContext& commands, ID3D12Resource* destination,\n'
   '                              const uevr::triview::PacketLayout& frame, ID3D12Resource* periphery);\n'),
 ],
 "src/mods/vr/D3D12Component.cpp": [
  ('    vr->get_openxr_runtime()->invalidate_duoview_scene();\n    this->duoview_compositors.clear();\n',
   '    vr->get_openxr_runtime()->invalidate_duoview_scene();\n    this->duoview_compositors.clear();\n'
   '    this->triview_compositors.clear();\n'),
  ('    this->duoview_compositors.clear();\n    this->contexts.clear();\n',
   '    this->duoview_compositors.clear();\n    this->triview_compositors.clear();\n    this->contexts.clear();\n'),
  # Automatic capture helper (member of D3D12Component), defined before the method that uses it.
  ('bool D3D12Component::ensure_2d_screen_textures(ID3D12Device* device, const D3D12_RESOURCE_DESC& base_desc) {',
   TRIVIEW_CAPTURE_IMPL + 'bool D3D12Component::ensure_2d_screen_textures(ID3D12Device* device, const D3D12_RESOURCE_DESC& base_desc) {'),
  ('                    } else if (stalker_exact) {\n                        copy_stalker_pair();\n'
   '                    } else if (native_stereo_packet == nullptr ||',
   '                    } else if (stalker_exact) {\n                        copy_stalker_pair();\n'
   '                    } else if (vr->is_triview_active() && m_game_tex.texture.Get() != nullptr &&\n'
   '                               m_scene_capture_tex.texture.Get() != nullptr &&\n'
   '                               (native_stereo_packet != nullptr ? native_stereo_packet->triview.valid : m_triview_last.valid)) {\n'
   '                        // Tri-View ID7: each eye = periphery underneath + own fovea on top, instead of\n'
   '                        // Joey\'s plain copy. Three textures, each image at its origin: main (left fovea),\n'
   '                        // capture (right fovea), Tri-View\'s periphery target. A Present without a new engine\n'
   '                        // packet recomposes the last packet. Pose and submission stay Native Stereo.\n'
   '                        if (native_stereo_packet != nullptr) {\n'
   '                            m_triview_last = native_stereo_packet->triview;\n'
   '                            m_triview_last_periphery = native_stereo_packet->triview_target != nullptr\n'
   '                                ? native_stereo_packet->triview_target->native : nullptr;\n'
   '                        }\n'
   '                        if (m_triview_capture != nullptr) { m_triview_capture->poll(); }\n'
   '                        const auto triview_frame = m_triview_last;\n'
   '                        ID3D12Resource* const triview_periphery = triview_frame.third ? m_triview_last_periphery.Get() : nullptr;\n'
   '                        bool triview_composed = false;\n'
   '                        m_openxr.copy((uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE, nullptr,\n'
   '                            [&](d3d12::CommandContext& commands, ID3D12Resource* destination) {\n'
   '                                if (!commands.ready() || destination == nullptr) { return; }\n'
   '                                auto& slot = m_openxr.triview_compositors[&commands];\n'
   '                                if (!slot) { slot = std::make_unique<uevr::triview::dx12::Compositor>(); }\n'
   '                                triview_composed = slot->record(device, commands.cmd_list.Get(),\n'
   '                                    m_game_tex.texture.Get(), m_scene_capture_tex.texture.Get(), triview_periphery,\n'
   '                                    destination, triview_frame, vr->triview_debug_mode());\n'
   '                                if (triview_composed) {\n'
   '                                    commands.has_commands = true;\n'
   '                                    triview_take_capture(commands, destination, triview_frame, triview_periphery);\n'
   '                                    if (native_stereo_packet != nullptr && native_stereo_hook != nullptr) {\n'
   '                                        if (native_frame_ticket) {\n'
   '                                            native_stereo_hook->record_native_frame_stage(*native_stereo_packet, native_frame_ticket,\n'
   '                                                frame_diag::Backend::d3d12, frame_diag::Runtime::openxr, frame_diag::Stage::copy_recorded,\n'
   '                                                0, 2, 0, m_scene_capture_tex.texture.Get(), destination);\n'
   '                                        }\n'
   '                                        native_stereo_hook->note_native_stereo_frame_packet_consumed(native_stereo_packet->serial);\n'
   '                                    }\n'
   '                                } else {\n'
   '                                    SPDLOG_WARNING_EVERY_N_SEC(2, "[TriView] Composite rejected ({}); showing Joey\'s copy", slot->error());\n'
   '                                    pre_render(commands, destination);\n'
   '                                }\n'
   '                            }, std::nullopt, D3D12_RESOURCE_STATE_RENDER_TARGET, nullptr);\n'
   '                        (triview_composed ? vr->m_triview_composites : vr->m_triview_composite_rejects)\n'
   '                            .fetch_add(1, std::memory_order_relaxed);\n'
   '                    } else if (native_stereo_packet == nullptr ||'),
  ('                    } else if (vr->is_using_mono()) {\n                        bool recorded = false;\n',
   '                    } else if (vr->is_using_mono()) {\n'
   '                        if (vr->is_triview_selected()) {\n'
   '                            SPDLOG_WARNING_EVERY_N_SEC(2, "[TriView][D3D12] Mono submit path taken while Tri-View is selected");\n'
   '                        }\n'
   '                        bool recorded = false;\n'),
  ('                               dune_using_hmd_mono_expansion) {\n                        m_openxr.copy((uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE, backbuffer.Get(), scene_source_state, nullptr);',
   '                               dune_using_hmd_mono_expansion) {\n'
   '                        if (vr->is_triview_selected()) {\n'
   '                            SPDLOG_WARNING_EVERY_N_SEC(2, "[TriView][D3D12] Plain backbuffer copy: active={} packet={} triview_valid={} last_valid={} game_tex={} capture_tex={}",\n'
   '                                vr->is_triview_active(), native_stereo_packet != nullptr,\n'
   '                                native_stereo_packet != nullptr && native_stereo_packet->triview.valid, m_triview_last.valid,\n'
   '                                m_game_tex.texture.Get() != nullptr, m_scene_capture_tex.texture.Get() != nullptr);\n'
   '                        }\n'
   '                        m_openxr.copy((uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE, backbuffer.Get(), scene_source_state, nullptr);'),
 ],
}

# VR.cpp implementations, appended like DuoView's configure_duoview().
VR_CPP_APPEND = '''
// Tri-View Stage 1 (rendering method ID 7). STALKER 2 + D3D12 + OpenXR, same gate as DuoView ID6.
bool VR::is_triview_active() const {
    if (!is_triview_selected() || !m_is_d3d12 || is_using_afr() || is_using_2d_screen()) return false;
    const auto runtime = get_runtime();
    if (!runtime || !runtime->is_openxr()) return false;
    static const bool stalker2 = [] {
        const auto path = utility::get_module_pathw(utility::get_executable());
        return path && uevr::stalker2_native::is_executable(*path);
    }();
    return stalker2;
}

// One layout per engine frame: eye projections, HMD render size, periphery/fovea settings and (S3) the PSVR2
// gaze, sampled once by the first hook of the frame and reused by every later hook of the same frame
// (projection crops, view rects, the packet), so the compositor always gets the windows the engine rendered.
std::optional<uevr::triview::Layout> VR::triview_layout() {
    const auto runtime = get_runtime();
    if (!runtime) return {};
    const auto left_projection = get_projection_matrix(VRRuntime::Eye::LEFT);
    const auto left = uevr::triview::tans_from_projection(left_projection);
    const auto right = uevr::triview::tans_from_projection(get_projection_matrix(VRRuntime::Eye::RIGHT));
    if (!left || !right) return {};
    const uint64_t frame = runtime->internal_frame_count;
    std::scoped_lock lock{m_triview_layout_mutex};
    if (m_triview_layout_cached && m_triview_layout_frame == frame &&
        m_triview_layout_cached->eye_width == get_hmd_width() && m_triview_layout_cached->eye_height == get_hmd_height()) {
        return m_triview_layout_cached;
    }
    std::optional<uevr::triview::GazeTan> gaze{};
    if (m_triview_eye_tracked->value()) {
        // Same PSVR2 reader and crop stability as DuoView ID6, with DuoView's gaze settings.
        auto frozen_projection = left_projection;
        const float near_plane = sdk::globals::get_near_clipping_plane();
        if (std::isfinite(near_plane) && near_plane > 0.f) frozen_projection[3][2] = near_plane;
        std::array<float, 16> frozen{};
        std::memcpy(frozen.data(), &frozen_projection[0][0], sizeof(frozen));
        const auto eye = get_eye_transform(0);
        const std::array<float, 9> optical{eye[0][0], eye[0][1], eye[0][2], eye[1][0], eye[1][1], eye[1][2],
            eye[2][0], eye[2][1], eye[2][2]};
        m_duoview_gaze.set_recovery_controls(static_cast<uint32_t>(m_duo_hold->value()),
            static_cast<uint32_t>(m_duo_reacquire->value()));
        const auto sample = m_duoview_gaze.read_uv(frozen, optical);
        m_triview_gaze_live.store(sample.has_value(), std::memory_order_relaxed);
        uevr::duoview::Settings settings{};
        settings.crop_width = settings.crop_height = m_triview_fovea_size->value();
        settings.eye_tracked = true;
        settings.gaze_offset_u = m_duo_offset_x->value();
        settings.gaze_offset_v = m_duo_offset_y->value();
        settings.gaze_micro_gain = m_duo_micro_gain->value();
        settings.gaze_breakout_radius = m_duo_breakout->value();
        settings.gaze_still_radius = m_duo_stillness->value();
        settings.gaze_relock_samples = static_cast<uint32_t>(m_duo_relock->value());
        // Test 2: without stabilisation the window followed raw gaze every frame (shaking). Use DuoView's
        // lock-until-saccade stabilisation, noise guard and pixel-grid snapping, always on for Tri-View.
        settings.stabilize_crop = true;
        settings.guard_fraction = m_duo_guard->value();
        settings.gaze_quant_pixels = static_cast<uint32_t>(m_duo_quant->value());
        settings.gaze_hold_ms = m_duo_hold->value();
        settings.gaze_reacquire_samples = m_duo_reacquire->value();
        const auto centre = m_triview_stability.update(uevr::duoview::FrameKey{1, frame}, get_hmd_width(),
            get_hmd_height(), settings, sample, GetTickCount64());
        if (sample.has_value() || centre.u != .5f || centre.v != .5f) {
            gaze = uevr::triview::GazeTan{left->left + centre.u * (left->right - left->left),
                                          left->top - centre.v * (left->top - left->bottom)};
        }
    } else {
        m_triview_gaze_live.store(false, std::memory_order_relaxed);
    }
    m_triview_layout_cached = uevr::triview::make_layout(get_hmd_width(), get_hmd_height(), *left, *right,
        m_triview_periphery_scale->value(), m_triview_fovea_size->value(), gaze);
    m_triview_layout_frame = frame;
    return m_triview_layout_cached;
}

void VR::triview_note_eye_pose(int32_t index, const double* rotation, const double* position) {
    if (index != 0 && index != 1) return;
    // UE builds eye 0, then eye 1, then the centre view in one pass: eye 0 invalidates last frame's
    // eye 1, so the centre camera can only be built from poses noted in the same frame.
    if (index == 0) { m_triview_eye_seen[1] = false; }
    auto& pose = m_triview_eye_pose[index];
    for (int i = 0; i < 3; ++i) { pose[i] = rotation[i]; pose[3 + i] = position[i]; }
    m_triview_eye_seen[index] = true;
}

bool VR::triview_fresh_start_due() {
    const uint64_t generation = mono_generation();
    if (m_triview_fresh_generation == generation) return false;
    m_triview_fresh_generation = generation;
    m_native_stereo_fix->value() = true; // keep Joey's own Native Fix switch consistent with Tri-View
    return true;
}

// UE builds view 2 right after views 0 and 1 in the same Draw, so these are this frame's eyes.
bool VR::triview_centre_pose(double* rotation, double* position) const {
    if (!m_triview_eye_seen[0] || !m_triview_eye_seen[1]) return false;
    for (int i = 0; i < 3; ++i) {
        rotation[i] = m_triview_eye_pose[0][i];
        position[i] = (m_triview_eye_pose[0][3 + i] + m_triview_eye_pose[1][3 + i]) * 0.5;
    }
    return true;
}
'''

FRONTEND = {
 "UEVR/RenderingModeOptions.cs": [
  ('        public const int DuoViewMono = 6;',
   '        public const int DuoViewMono = 6;\n        public const int TriView = 7;'),
  ('            result.Add(DuoViewMono.ToString(), "DuoView Mono (Eye Tracked - Experimental)");',
   '            result.Add(DuoViewMono.ToString(), "DuoView Mono (Eye Tracked - Experimental)");\n'
   '            result.Add(TriView.ToString(), "' + LABEL + '");'),
 ],
 "tests/RenderingModes/Program.cs": [
  ('for (int id = 0; id <= 6; ++id) {', 'for (int id = 0; id <= 7; ++id) {'),
  ('bool supported = id < 3 || id == 5 || id == 6 || dibr;',
   'bool supported = id < 3 || id == 5 || id == 6 || id == 7 || dibr;'),
  ('"4", "5", "6", "99", "-1"', '"4", "5", "6", "7", "99", "-1"'),
  ('    if (choices.ContainsKey("99")) {',
   '    if (choices["7"] != "' + LABEL + '") {\n'
   '        throw new Exception("Tri-View must keep serialized ID 7");\n'
   '    }\n'
   '    if (choices.ContainsKey("99")) {'),
 ],
}


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_edits(root, file_map):
    for rel, edits in file_map.items():
        path = root / rel
        text = path.read_text(encoding="utf-8-sig")
        for before, after in edits:
            count = text.count(before)
            if count != 1:
                raise RuntimeError(f"{rel}: expected one anchor, found {count}: {before[:110]!r}")
            text = text.replace(before, after, 1)
        path.write_text(text, encoding="utf-8", newline="")


def tracked_state(root):
    changed = set(git(root, "diff", "--name-only", "HEAD").splitlines())
    added = set(git(root, "ls-files", "--others", "--exclude-standard").splitlines())
    return changed, added


def apply(args):
    backend, frontend, duoview, evidence = map(Path, args.paths)
    evidence.mkdir(parents=True, exist_ok=True)
    if git(backend, "rev-parse", "HEAD") != "5ac7edc207866569334175e4ed8a7517971547f6":
        raise RuntimeError("Unexpected Joey backend revision")
    if git(frontend, "rev-parse", "HEAD") != "60be4b0f9a646109fd9fdf448bacd41477234091":
        raise RuntimeError("Unexpected Joey frontend revision")
    changed, added = tracked_state(backend)
    if changed != V207_EDITED or added != V207_ADDED:
        raise RuntimeError(f"Backend is not the exact v207 state: {sorted((changed ^ V207_EDITED) | (added ^ V207_ADDED))}")

    vr = backend / "src/mods/vr"
    for name in MODULE_FILES + ("TriViewShaderSource.hpp",):
        if (vr / name).exists():
            raise RuntimeError(f"Refusing to overwrite {vr / name}")
    for name in MODULE_FILES:
        (vr / name).write_bytes((duoview / "triview" / name).read_bytes())
    subprocess.run([sys.executable, str(duoview / "triview" / "embed_triview_shader.py"),
                    str(vr / "TriViewShaderSource.hpp")], check=True)

    apply_edits(backend, BACKEND)
    cpp = backend / "src/mods/VR.cpp"
    cpp.write_text(cpp.read_text(encoding="utf-8") + VR_CPP_APPEND, encoding="utf-8", newline="")
    apply_edits(frontend, FRONTEND)

    changed, added = tracked_state(backend)
    expected_changed = V207_EDITED | TRIVIEW_EDITED
    expected_added = V207_ADDED | TRIVIEW_ADDED
    if changed != expected_changed or added != expected_added:
        raise RuntimeError(f"Unexpected backend paths: {sorted((changed ^ expected_changed) | (added ^ expected_added))}")
    fchanged, fadded = tracked_state(frontend)
    if fchanged - (FRONTEND_EDITED | FRONTEND_GENERATED) or not FRONTEND_EDITED <= fchanged or fadded:
        raise RuntimeError(f"Unexpected frontend paths: {sorted(fchanged | fadded)}")

    hashes = {"backend": {p: sha(backend / p) for p in sorted(expected_changed | expected_added)},
              "frontend": {p: sha(frontend / p) for p in sorted(FRONTEND_EDITED)}}
    (evidence / "triview-stage1-hashes.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    print("Tri-View Stage 1 applied: rendering method ID 7 (Native Fix + centre periphery); modes 0-6 gated off.")


def verify(args):
    backend, evidence = map(Path, args.paths)
    recorded = json.loads((evidence / "triview-stage1-hashes.json").read_text(encoding="utf-8"))
    for rel, digest in recorded["backend"].items():
        if sha(backend / rel) != digest:
            raise RuntimeError(f"{rel} changed during the build")
    print(f"Tri-View Stage 1 source unchanged after build ({len(recorded['backend'])} backend files).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("paths", nargs="+")
    a = parser.parse_args()
    if a.verify:
        if len(a.paths) != 2:
            sys.exit("usage: apply_triview_stage1.py --verify BACKEND EVIDENCE")
        verify(a)
    else:
        if len(a.paths) != 4:
            sys.exit("usage: apply_triview_stage1.py BACKEND FRONTEND DUOVIEW_DIR EVIDENCE")
        apply(a)
