#!/usr/bin/env python3
"""Source-contract checks for the generated ID7 bootstrap (no game execution)."""
from pathlib import Path
import sys
import unittest

BACKEND = Path(sys.argv.pop(1)) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "backend"
SOURCE = (BACKEND / "src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8")
HEADER = (BACKEND / "src/mods/VR.hpp").read_text(encoding="utf-8")


def region(begin, end):
    start = SOURCE.index(begin)
    return SOURCE[start:SOURCE.index(end, start)]


class TriViewBootstrapTests(unittest.TestCase):
    def test_family_layout_precedes_all_id7_family_getters(self):
        ctor = region("        auto* qv_init_family=init_options->get_view_family();", "        const auto qv_original_pass=")
        resolved = ctor.index("sdk::FSceneViewFamily::update_offsets(qv_init_family,")
        guarded = ctor.index("if (!qv_family_layout_ready)")
        fallback = ctor.index("constructor_hook.unsafe_call<sdk::FSceneView*>", guarded)
        self.assertLess(resolved, guarded)
        self.assertLess(fallback, ctor.index("qv_init_family->get_views()"))
        self.assertLess(fallback, ctor.index("qv_init_family->get_render_target()"))
        self.assertNotIn("constructed(", ctor[:fallback])
        self.assertIn("note_scene_view_family_offsets_ready()", ctor)

    def test_localplayer_bootstrap_precedes_projection_return(self):
        projection = region("__forceinline Matrix4x4f* FFakeStereoRenderingHook::calculate_stereo_projection_matrix(", "__forceinline void FFakeStereoRenderingHook::render_texture_render_thread(")
        self.assertEqual(projection.count("bool ghosting_bootstrap_ready = false;"), 1)
        self.assertLess(projection.index("bool ghosting_bootstrap_ready"), projection.index("if (vr->is_quadview_layout_active())"))
        self.assertLess(projection.index("Inserting midhook after CalculateStereoProjectionMatrix"), projection.index("if (vr->is_quadview_layout_active())"))
        self.assertIn("vr->is_native_stereo_fix_enabled() || qv_needs_localplayer_bootstrap", projection)
        self.assertIn("vr->requested_rendering_method() == VR::RenderingMethod::QUAD_VIEWS_STEREO", projection)
        self.assertIn("vr->is_quadview_supported_title()", projection)
        self.assertIn("!vr->should_skip_post_init_properties() && wants_localplayer_bootstrap", projection)
        self.assertIn("!stalker2_uses_lazy_synced_viewstates()", projection)
        self.assertNotIn("get_module_path", projection[projection.index("const bool qv_needs_localplayer_bootstrap"):projection.index("const bool native_needs_localplayer_bootstrap")])

    def test_post_init_retains_two_view_allocation_and_native_gate(self):
        desired = region("uint32_t FFakeStereoRenderingHook::get_desired_number_of_views_hook(", "void FFakeStereoRenderingHook::post_calculate_stereo_projection_matrix(")
        self.assertIn("if (g_hook->m_sceneview_data.inside_post_init_properties) {\n        return 2;\n    }", desired)
        self.assertLess(desired.index("inside_post_init_properties"), desired.index("if (vr->is_quadview_mode_selected())"))
        self.assertIn("if (is_quadview_mode_selected() || is_mono_transition_quiescing()) { return false; }", HEADER)
        post_init = region("void FFakeStereoRenderingHook::post_init_properties(", "bool VRRenderTargetManager_Base::")
        self.assertIn("if (stalker2_uses_lazy_synced_viewstates())", post_init)

    def test_texture_identity_and_generation_proofs_remain(self):
        validator = region("std::optional<ValidatedNativeFixTextureChain> validate_native_fix_texture_chain(", "bool is_ue_5_5_dx_backend()")
        self.assertNotIn("FRHITexture2D::set_vtable", validator)
        self.assertIn("expected_rhi_vtable == nullptr", validator)
        self.assertIn("*reinterpret_cast<void**>(rhi_texture) != expected_rhi_vtable", validator)
        self.assertIn("resource_device.Get() != expected_device", validator)
        self.assertIn("desc.Width != expected_width || desc.Height != expected_height", validator)
        target = region("bool VRRenderTargetManager_Base::ensure_quadview_native_target_set(", "void VRRenderTargetManager_Base::retire_quadview_native_target_set()")
        self.assertIn("build->generation!=quadview_native_target_generation.load", target)
        self.assertIn("validate_native_fix_texture_chain", target)
        self.assertIn("quadview_native_targets_live(*current)", target)

    def test_bootstrap_logging_is_throttled(self):
        for tag in ("LocalPlayer attempted=", "family_layout=", "RHI class_ready="):
            at = SOURCE.index('"[QuadViews][Bootstrap] ' + tag)
            self.assertIn("SPDLOG_INFO_EVERY_N_SEC(2,", SOURCE[at-70:at])


if __name__ == "__main__":
    unittest.main()
