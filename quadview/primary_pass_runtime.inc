    // ID7 renders four independent singleton families. Classify each source
    // consistently before LocalPlayer/post-process logic observes StereoPass,
    // not only while FSceneView's constructor is temporarily intercepted.
    // StereoViewIndex remains 0..3: this changes no pose, projection or history.
    if (const auto& vr=VR::get(); vr && g_hook &&
        vr->is_quadview_primary_pass_enabled() && vr->is_quadview_supported_title() &&
        vr->is_hmd_active() && g_hook->is_in_viewport_client_draw() &&
        !g_hook->quadview_native_build_context.active &&
        !g_hook->m_sceneview_data.inside_post_init_properties &&
        vr->is_quadview_layout_active() &&
        view_index>=0 && view_index<4 &&
        vr->quadview_native_target_set(vr->quadview_producer_key())) {
        SPDLOG_INFO_EVERY_N_SEC(2,"[QuadViews][Shading] source index={} eye={} role={} pass=PRIMARY from initial selection; independent history retained",
            view_index,view_index&1,view_index<2?"context":"focus");
        return EStereoscopicPass::eSSP_PRIMARY;
    }
