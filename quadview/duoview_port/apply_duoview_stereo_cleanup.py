"""B318 stereo cleanup B (intentional behavioral changes).

Generated-only overlay, applied last after B318 source-fit. Do not run against
repo inputs directly; the pinned UEVR generator must create these postimages.

- Old profile keys remain loadable for one-time depth smoothing migration.
- Symmetric source-seed depth slope responds monotonically to close/far values.
- M3/M9/fill/M6/M7 effect settings are removed from *effective* stereo frames.
- Stereo history textures are not allocated; separate B40 seam history remains.
"""
from pathlib import Path
import re
import sys


def once(src, old, new, label):
    n = src.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected one exact B318 anchor, found {n}")
    return src.replace(old, new, 1)


def edit(path, f):
    src = path.read_text(encoding='utf-8')
    out = f(src)
    if out == src:
        raise RuntimeError(f"{path}: no changes")
    path.write_text(out, encoding='utf-8')


def ui_header(src):
    src=once(src,
        '    const ModSlider::Ptr m_duo_stereo_softness{ModSlider::create(generate_name("DuoViewStereoEdgeSoftness"), .25f, .99f, .5f)};',
        '''    // Read-only legacy sliders survive solely to migrate older INI values.
    const ModSlider::Ptr m_duo_stereo_softness{ModSlider::create(generate_name("DuoViewStereoEdgeSoftness"), .25f, .99f, .5f)};
    const ModToggle::Ptr m_duo_depth_schema_v2{ModToggle::create(generate_name("DuoStereoDepthSchemaV2"),false)};
    // Preserve non-linear legacy transition response until the user edits a V2 depth slider.
    const ModToggle::Ptr m_duo_depth_legacy_curve{ModToggle::create(generate_name("DuoStereoLegacyCurveV2"),false)};
    const ModSlider::Ptr m_duo_depth_close{ModSlider::create(generate_name("DuoDepthSmoothClose"),0.f,1.f,0.f)};
    const ModSlider::Ptr m_duo_depth_far{ModSlider::create(generate_name("DuoDepthSmoothFar"),0.f,1.f,.75f)};''',
        'new depth controls / schema')
    src=once(src,
        '            *m_duo_stereo_near, *m_duo_stereo_softness,',
        '            *m_duo_stereo_near, *m_duo_stereo_softness,\n            *m_duo_depth_schema_v2, *m_duo_depth_legacy_curve, *m_duo_depth_close, *m_duo_depth_far,',
        'register new persistent controls')
    return src


def ui_cpp(src):
    src = once(src,
        '                    m_duo_stereo_near->value()=1.f; m_duo_stereo_softness->value()=.5f;',
        '''                    m_duo_stereo_near->value()=1.f; m_duo_stereo_softness->value()=.5f;
                    m_duo_depth_close->value()=0.f; m_duo_depth_far->value()=0.f;
                    m_duo_depth_schema_v2->value()=true;
                    m_duo_depth_legacy_curve->value()=false;''',
        'reset new depth fields')
    start = src.index('                m_duo_stereo->draw("Synthetic stereo (M1, experimental)");')
    end = src.index('                } else {\n                    m_duo_shared_eye->draw("Same image for both eyes (v208)");',start)
    new_ui = '''                m_duo_stereo->draw("Synthetic stereo");
                if (m_duo_stereo->value()) {
                    const float old_close=m_duo_depth_close->value();
                    const float old_far=m_duo_depth_far->value();
                    m_duo_depth_close->draw("Close depth smoothing (0 sharp, 1 smooth)");
                    m_duo_depth_far->draw("Far depth smoothing (0 sharp, 1 smooth)");
                    // The old piecewise-clamped distance curve is retained only
                    // until the first intentional edit of a new depth slider.
                    if (old_close!=m_duo_depth_close->value() || old_far!=m_duo_depth_far->value())
                        m_duo_depth_legacy_curve->value()=false;
                    m_duo_m8_near_m->draw("Depth transition starts (metres)");
                    m_duo_m8_far_m->draw("Depth transition ends (metres)");
                    if (ImGui::TreeNode("Stereo calibration and developer diagnostics")) {
                        m_duo_stereo_strength->draw("Stereo strength");
                        m_duo_stereo_near->draw("Near depth limit (metres, 0 off)");
                        m_duo_m4_fovea_grid->draw("Full-resolution foveal depth (strict-paired M4; OFF = coarse)");
                        m_duo_m21_depth_debug->draw("Depth diagnostic (developer-only, adds debug work)");
                        ImGui::TreePop();
                    }
'''
    src = src[:start]+new_ui+src[end:]
    marker = '    const auto current = m_duoview.settings();\n    uevr::duoview::Settings candidate{'
    src = once(src,marker,
        '''    const auto current = m_duoview.settings();
    // Once per legacy profile, migrate effective M4 endpoint *slopes*, not
    // numeric old sliders. Old distance-OFF maps to constant smoothing.
    // Preserve the old piecewise/clamped curve via the retired M9 flag lane
    // until the first new smoothing-slider edit. This preserves all distances.
    if (!m_duo_depth_schema_v2->value()) {
        const float base=(std::clamp)(m_duo_stereo_softness->value(),.25f,.99f);
        const bool old_distance=m_duo_m8_distance->value();
        const auto translate=[&](float old_edge) {
            const float weight=(std::clamp)(old_edge,0.f,1.f);
            const float old_factor=old_distance ? (2.f-1.65f*weight) : 1.f;
            const float old_relative=(std::clamp)(base*old_factor/.99f,0.f,1.f);
            return (std::clamp)((1.f-old_relative)/.90f,0.f,1.f);
        };
        m_duo_depth_close->value()=translate(m_duo_m8_edge_near->value());
        m_duo_depth_far->value()=translate(m_duo_m8_edge_far->value());
        m_duo_depth_schema_v2->value()=true;
        m_duo_depth_legacy_curve->value()=true;
        SPDLOG_INFO("[DuoView] Stereo depth profile V2 migrated (close={}, far={}), legacy transition kept until edit; obsolete fill/edge/temporal modes disabled",
            m_duo_depth_close->value(), m_duo_depth_far->value());
    }
    const bool stereo_ready=m_duo_stereo->value() &&
        m_duo_stereo_bootstrap_ready.load(std::memory_order_acquire);
    uevr::duoview::Settings candidate{''',
        'one-time migration in configure')
    src = once(src,
        '''        .stereo_softness=m_duo_stereo_softness->value(),
        .m2_fovea_depth=m_duo_m2_fovea_depth->value() || m_duo_m4_fovea_grid->value(),
        .m25_fine_mode=m_duo_m4_fovea_grid->value() ? 1u : uint32_t(m_duo_m25_fine_mode->value()>=.5f),
        .m3_edges=m_duo_m3_edges->value(),
        .m3_fold_sharpness=m_duo_m3_fold->value(),
        .m3_fill=m_duo_m3_fill->value(),
        .m3_jitter_mode=uint32_t((std::clamp)(m_duo_m3_jitter->value(),0,2)),''',
        '''        // True mono distance-fade keeps its old M1 slope; stereo V2 uses
        // a normalized 0.99 maximum with safe per-eye slope bounds.
        .stereo_softness=(stereo_ready && !m_duo_depth_legacy_curve->value())
            ? .99f : m_duo_stereo_softness->value(),
        .m2_fovea_depth=m_duo_m4_fovea_grid->value(),
        .m25_fine_mode=0u, // M4 already uses strict frame pairing, not M25
        .m3_edges=stereo_ready ? false : m_duo_m3_edges->value(),
        .m3_fold_sharpness=stereo_ready ? .95f : m_duo_m3_fold->value(),
        .m3_fill=stereo_ready ? false : m_duo_m3_fill->value(),
        .m3_jitter_mode=stereo_ready ? 0u : uint32_t((std::clamp)(m_duo_m3_jitter->value(),0,2)),''',
        'retire M2-only, directional M3, old slope controls')
    src = once(src,
        '''        .edge_history=m_duo_edge_history->value(),
        .fill_history=m_duo_fill_history->value(),
        .fill_blur_px=m_duo_fill_blur->value(),
        .edge_reach_px=m_duo_edge_reach->value(),
        .m8_distance=m_duo_m8_distance->value(),''',
        '''        .edge_history=0.f, .fill_history=0.f,
        .fill_blur_px=0.f, .edge_reach_px=2.f,
        .m8_distance=stereo_ready ?
            (!m_duo_depth_legacy_curve->value() || m_duo_m8_distance->value()) : m_duo_m8_distance->value(),''',
        'retire temporal and force stereo distance policy')
    src = once(src,
        '''        .m8_edge_near=m_duo_m8_edge_near->value(), .m8_edge_far=m_duo_m8_edge_far->value(),
        .m8_fill_near=m_duo_m8_fill_near->value(), .m8_fill_far=m_duo_m8_fill_far->value(),
        .m9_eye_near=m_duo_m9_eye_near->value(), .m9_eye_far=m_duo_m9_eye_far->value(),''',
        '''        .m8_edge_near=(stereo_ready && !m_duo_depth_legacy_curve->value())
            ? m_duo_depth_close->value() : m_duo_m8_edge_near->value(),
        .m8_edge_far=(stereo_ready && !m_duo_depth_legacy_curve->value())
            ? m_duo_depth_far->value() : m_duo_m8_edge_far->value(),
        .m8_fill_near=stereo_ready ? 0.f : m_duo_m8_fill_near->value(),
        .m8_fill_far=stereo_ready ? 0.f : m_duo_m8_fill_far->value(),
        // M9 is retired in stereo. Its unused x lane carries the legacy marker.
        .m9_eye_near=stereo_ready ? (m_duo_depth_legacy_curve->value() ? 1.f : 0.f) : m_duo_m9_eye_near->value(),
        .m9_eye_far=stereo_ready ? 0.f : m_duo_m9_eye_far->value(),''',
        'retire M8 fill and M9')
    src = once(src,
        '''        .m21_jitter_correct=m_duo_m21_jitter->value(),
        .m24_vertical_taper=m_duo_m24_vertical->value(),''',
        '''        .m21_jitter_correct=stereo_ready ? false : m_duo_m21_jitter->value(),
        .m24_vertical_taper=stereo_ready ? 0.f : m_duo_m24_vertical->value(),''',
        'retire jitter and vertical taper')
    return src


def geometric_shader(src):
    src = once(src,
        'return lerp(2.0,.35,saturate(smoothness));',
        'return lerp(M9PerEye.x>.5 ? 2.0 : 1.0,\n                M9PerEye.x>.5 ? .35 : .10,saturate(smoothness));',
        'monotone M8 scale')
    src = once(src,
        'const float proposed=original*lerp(2.0,.35,saturate(smoothness));',
        'const float proposed=original*lerp(M9PerEye.x>.5 ? 2.0 : 1.0,\n            M9PerEye.x>.5 ? .35 : .10,saturate(smoothness));',
        'monotone M8 adjusted penalty')
    # Preserve full-grid fixed penalty in the old *mono* M1 path, but use the
    # source-origin M8 policy for coarse synthetic stereo as well as M4.
    src = once(src,
        '        M1Row[x] = knee > 0.0 ? nearDepth : min(nearDepth, M1Filter.y);',
        '''        M1Row[x] = knee > 0.0 ? nearDepth : min(nearDepth, M1Filter.y);
        // Skip the extra per-seed work for existing legacy profiles.
        if(M8Distance.z>.5 && M9PerEye.x<=.5)
            M8Scale[x] = M8SeedScale(M1Row[x]);''',
        'coarse per-seed slope initialization')
    old = '''        for (uint step = 1; step < w && float(step-1)*M1Filter.x < limit; step *= 2) {
            for (uint x = lane; x < w; x += 128) {
                const float penalty = float(step)*M1Filter.x;
                const float l = x >= step ? M1Row[x-step] - penalty : 0.0;
                const float r = x+step < w ? M1Row[x+step] - penalty : 0.0;
                M1Next[x] = max(M1Row[x], max(l,r));
            }
            GroupMemoryBarrierWithGroupSync();
            for (uint x = lane; x < w; x += 128) M1Row[x] = M1Next[x];
            GroupMemoryBarrierWithGroupSync();
        }'''
    new = '''        const bool adaptive=M8Distance.z>.5 && M9PerEye.x<=.5;
        const float eyeMax=max(max(abs(M1Eye.x),abs(M1Eye.y)),.00001);
        const float slopeCap=.99/max(eyeMax*float(w),.00001);
        const float minimumSlope=adaptive ? slopeCap*.10 : M1Filter.x;
        for (uint step=1; step<w && float(step-1)*minimumSlope<limit; step*=2) {
            for (uint x=lane; x<w; x+=128) {
                const uint left=x>=step ? x-step : x;
                const uint right=x+step<w ? x+step : x;
                const float l=x>=step ? M1Row[left]-float(step)*
                    (adaptive ? slopeCap*M8Scale[left] : M1Filter.x) : 0.;
                const float r=x+step<w ? M1Row[right]-float(step)*
                    (adaptive ? slopeCap*M8Scale[right] : M1Filter.x) : 0.;
                const float current=M1Row[x];
                M1Next[x]=max(current,max(l,r));
                if (adaptive) {
                    float winner=M8Scale[x];
                    if (l>current && l>=r) winner=M8Scale[left];
                    else if (r>current && r>l) winner=M8Scale[right];
                    M8NextScale[x]=winner;
                }
            }
            GroupMemoryBarrierWithGroupSync();
            for (uint x=lane; x<w; x+=128) {
                M1Row[x]=M1Next[x];
                if (adaptive) M8Scale[x]=M8NextScale[x];
            }
            GroupMemoryBarrierWithGroupSync();
        }'''
    src = once(src,old,new,'coarse slope envelope')
    # In M4, new smooth=1 requires the .10 minimum bound, otherwise the loop
    # could terminate prematurely and omit valid distant propagation.
    src = src.replace('(M8Distance.z>.5 ? .35 : 1.)',
                      '(M8Distance.z>.5 ? (M9PerEye.x>.5 ? .35 : .10) : 1.)')
    if src.count('(M8Distance.z>.5 ? .35 : 1.)'):
        raise RuntimeError('old 0.35 M4 minimum remains')
    return src


def remove_stereo_history_shader(src):
    # All six M4 kernels (production and diagnostic alternatives) share the
    # same history block. The 2x2 near-max seed stays; far-min is no longer used.
    pattern = re.compile(r'''        \[branch\] if \(M7Controls\.w>\.5\) \{\n.*?            M7CurrentWrite\[uint2\(x,group\.x\)\]=float4\(fine,representativeDepth,packed,rawNear\);\n        \}\n''',re.S)
    src,n=pattern.subn('',src)
    if n!=6: raise RuntimeError(f'M7 condition/probe history blocks: {n}/6')
    if src.count('float fine=0.0, farDepth=1.e9;')!=6:
        raise RuntimeError('unexpected M4 near/far seed layout')
    src=src.replace('float fine=0.0, farDepth=1.e9;','float fine=0.0;')
    if src.count('                farDepth=min(farDepth,d);')!=6:
        raise RuntimeError('unexpected M4 far-depth reductions')
    src=src.replace('                farDepth=min(farDepth,d);\n','')
    # Remove dead reprojection/packing code. This excludes only M6/M7 synthetic
    # history, not B40 seam history or any capture/VectorXR history.
    start=src.index('// Both ping-pong images store unconditioned history')
    end=src.index('[numthreads(128,1,1)]\nvoid CSConditionM4(',start)
    src=src[:start]+'// M6/M7 synthetic stereo history retired by V2.\n\n'+src[end:]
    return src


def raster_shader(src):
    start=src.index('Texture2D<float4> M7CurrentHistory : register(t10);')
    end=src.index('\n#endif',start)
    src=src[:start]+'// M6/M7 stereo color history retired; B40 seam history unaffected.\n'+src[end:]
    start=src.index('#ifdef DUOVIEW_M1_RASTER\n        [branch] if (DebugViewMode==0 && fill.z>.001')
    end=src.index('#endif',start)+len('#endif')
    src=src[:start]+'// Stereo V2 uses a direct warp and no synthetic disocclusion color fill.\n'+src[end:]
    return src


def backend_history(src):
    src = once(src,
        '    std::array<ComPtr<ID3D12Resource>,2> temporal;\n','',
        'remove two 1024x1024 float4 histories')
    start=src.index('        desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;\n        desc.Width=desc.Height=M1Resources::grid_limit;',src.index('struct B40MonoHistory'))
    end=src.index('        return state;',start)
    # First return state appears in old allocation failure branch; use closing
    # class's own boundary as the limit instead.
    end=src.index('        return state;\n    }\n};',start)
    src=src[:start]+src[end:]
    # Keep B40 buffer and fine-depth key; retire only synthetic history frames.
    begin=src.index('        const bool no_fovea_fill=')
    finish=src.index('        const auto& color_desc=',begin)
    src=src[:begin]+'''        // Stereo temporal history retired. Keep B40 seam and strict fine-frame
        // ownership completely independent of this former color/edge cache.
        constexpr bool write_history=false;
        const FineDepthHistoryFrame* previous=nullptr;
'''+src[finish:]
    src=once(src,
        '''                settings.edge_history,fill_history_effective,fill_blur_effective,
                settings.edge_reach_px,color_extent,''',
        '''                0.f,0.f,0.f,
                2.f,color_extent,''',
        'zero formerly live synthetic edge/fill history arguments')
    start=src.index('        auto* history_output=write_history && m1_active')
    end=src.index('        // GPU lifetime remains bound to the exact retired OpenXR command slot,',start)
    src=src[:start]+'''        // No synthetic stereo history textures or per-frame descriptor writes.
        // Reserved t9/t10/u6 entries are null descriptors initialized at setup.
        history_read_=false;
'''+src[end:]
    src=once(src,
        '''        const auto fovea_sample_state=history_output && fill_history_effective>0.f
            ? D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE : sample_state;''',
        '''        const auto fovea_sample_state=sample_state;''',
        'remove obsolete M7 source transition')
    src=once(src,
        '''                constexpr auto history_read=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE |
                    D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
                if (history_output) transition(cmd,history_output,history_read,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
                if(!m4_probe_skip) {''',
        '''                if(!m4_probe_skip) {''',
        'remove M7 UAV transition before M4')
    src=once(src,
        '''                if (history_output) transition(cmd,history_output,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,history_read);
                bool m4_do_vertical=m1_.vertical_active;''',
        '''                bool m4_do_vertical=m1_.vertical_active;''',
        'remove M7 UAV transition after M4')
    start=src.index('        if (history_output) {\n            next_fine_depth_=')
    end=src.index('        return true;\n    }',start)
    src=src[:start]+'''        // Fine capture pairing is validated upstream on each frame; no M6/M7
        // previous-frame state or color packet is carried to the next slot.
        next_fine_depth_={};
'''+src[end:]
    # Retain descriptor-table count and root layout for raster & compute ABI.
    # Populate unused descriptors with legal NULL views at setup, not per-frame.
    src=once(src,
        '''        m6_previous_srv_=desc_cpu;
        desc_cpu.ptr+=srv_descriptor_increment_; // [14] t10 new history
        m7_current_srv_=desc_cpu;''',
        '''        m6_previous_srv_=desc_cpu;
        device->CreateShaderResourceView(nullptr,&tile_srv,desc_cpu);
        desc_cpu.ptr+=srv_descriptor_increment_; // [14] t10 unused history
        m7_current_srv_=desc_cpu;
        device->CreateShaderResourceView(nullptr,&tile_srv,desc_cpu);''',
        'null shader resource descriptors for retired history')
    src=once(src,
        '''        m7_current_uav_=desc_cpu;
        direct_xr_rtv_cpu_=rtv_cpu_start_;''',
        '''        m7_current_uav_=desc_cpu;
        D3D12_UNORDERED_ACCESS_VIEW_DESC unused_history_uav{};
        unused_history_uav.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;
        unused_history_uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
        device->CreateUnorderedAccessView(nullptr,nullptr,&unused_history_uav,desc_cpu);
        direct_xr_rtv_cpu_=rtv_cpu_start_;''',
        'null UAV descriptor for retired history')
    return src


def apply(backend,shaders):
    edit(backend/'src/mods/VR.hpp',ui_header)
    edit(backend/'src/mods/VR.cpp',ui_cpp)
    edit(shaders/'DuoViewM1Stereo.hlsl',lambda s:remove_stereo_history_shader(geometric_shader(s)))
    edit(shaders/'DuoViewNativeCompositeRaster.hlsl',raster_shader)
    edit(backend/'src/mods/vr/DuoViewD3D12.hpp',backend_history)


if __name__=='__main__':
    if len(sys.argv)!=3:
        raise SystemExit('usage: apply_duoview_stereo_cleanup.py <backend> <shaders>')
    apply(Path(sys.argv[1]),Path(sys.argv[2]))
    print('stereo cleanup B: monotone close/far depth, legacy migration, no synthetic M6/M7')
