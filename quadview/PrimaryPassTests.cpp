#include <cassert>
#include <cstdint>

enum class EStereoscopicPass : uint8_t {
    eSSP_FULL = 0,
    eSSP_PRIMARY = 1,
    eSSP_SECONDARY = 2,
};

struct FakeVR {
    int mode{};
    bool enabled{true};
    bool supported_title{true};
    bool hmd_active{true};
    bool layout_active{};
    bool native_targets_ready{};

    static FakeVR* instance;
    static FakeVR* get() { return instance; }

    bool is_quadview_primary_pass_enabled() const { return enabled; }
    bool is_quadview_supported_title() const { return supported_title; }
    bool is_hmd_active() const { return hmd_active; }
    bool is_quadview_layout_active() const { return layout_active; }
    uint64_t quadview_producer_key() const { return 1; }
    const int* quadview_native_target_set(uint64_t key) const {
        return key == 1 && native_targets_ready ? &sentinel : nullptr;
    }

private:
    int sentinel{};
};

FakeVR* FakeVR::instance{};
using VR = FakeVR;

struct FakeHook {
    bool inside_viewport_draw{};
    struct { bool active{}; } quadview_native_build_context;
    struct { bool inside_post_init_properties{}; } m_sceneview_data;
    bool is_in_viewport_client_draw() const { return inside_viewport_draw; }
};

FakeHook* g_hook{};

#define SPDLOG_INFO_EVERY_N_SEC(...) ((void)0)

static EStereoscopicPass production_get_view_pass_for_index(
    FakeVR& vr, FakeHook& hook, bool stereo_requested, int32_t view_index)
{
    FakeVR::instance = &vr;
    g_hook = &hook;

    if (!stereo_requested || view_index < 0) {
        return EStereoscopicPass::eSSP_FULL;
    }

#include "primary_pass_runtime.inc"

    return view_index % 2 == 0
        ? EStereoscopicPass::eSSP_PRIMARY
        : EStereoscopicPass::eSSP_SECONDARY;
}

static void expect_original_pass(FakeVR& vr, FakeHook& hook, int32_t index) {
    const auto expected = index % 2 == 0
        ? EStereoscopicPass::eSSP_PRIMARY
        : EStereoscopicPass::eSSP_SECONDARY;
    assert(production_get_view_pass_for_index(vr, hook, true, index) == expected);
}

int main() {
    FakeVR vr{};
    FakeHook hook{};
    hook.inside_viewport_draw = true;
    vr.supported_title = true;
    vr.enabled = true;
    vr.native_targets_ready = true;

    // The candidate only changes the four explicit ID7 source indices.
    for (int mode = 0; mode <= 7; ++mode) {
        vr.mode = mode;
        vr.layout_active = mode == 7;
        for (int32_t index = 0; index <= 5; ++index) {
            const auto actual = production_get_view_pass_for_index(vr, hook, true, index);
            const auto expected = mode == 7 && index < 4
                ? EStereoscopicPass::eSSP_PRIMARY
                : index % 2 == 0
                    ? EStereoscopicPass::eSSP_PRIMARY
                    : EStereoscopicPass::eSSP_SECONDARY;
            assert(actual == expected);
        }
    }

    vr.mode = 7;
    vr.layout_active = true;

    // Existing full-pass behavior remains for negative indices and stereo-off.
    for (int32_t index = -3; index < 0; ++index) {
        assert(production_get_view_pass_for_index(vr, hook, true, index) ==
               EStereoscopicPass::eSSP_FULL);
    }
    for (int32_t index = 0; index < 6; ++index) {
        assert(production_get_view_pass_for_index(vr, hook, false, index) ==
               EStereoscopicPass::eSSP_FULL);
    }

    // Every missing eligibility condition restores the old P/S parity behavior.
    vr.enabled = false;
    for (int32_t index = 0; index < 6; ++index) expect_original_pass(vr, hook, index);
    vr.enabled = true;

    hook.inside_viewport_draw = false;
    for (int32_t index = 0; index < 6; ++index) expect_original_pass(vr, hook, index);
    hook.inside_viewport_draw = true;

    vr.native_targets_ready = false;
    for (int32_t index = 0; index < 6; ++index) expect_original_pass(vr, hook, index);
    vr.native_targets_ready = true;

    vr.supported_title = false;
    for (int32_t index = 0; index < 6; ++index) expect_original_pass(vr, hook, index);
    vr.supported_title = true;

    vr.hmd_active = false;
    for (int32_t index = 0; index < 6; ++index) expect_original_pass(vr, hook, index);
    vr.hmd_active = true;

    hook.quadview_native_build_context.active = true;
    for (int32_t index = 0; index < 6; ++index) expect_original_pass(vr, hook, index);
    hook.quadview_native_build_context.active = false;

    hook.m_sceneview_data.inside_post_init_properties = true;
    for (int32_t index = 0; index < 6; ++index) expect_original_pass(vr, hook, index);
    hook.m_sceneview_data.inside_post_init_properties = false;

    vr.layout_active = false;
    for (int32_t index = 0; index < 6; ++index) expect_original_pass(vr, hook, index);

    return 0;
}
