"""Guarded R6 depth tools. Apply after the eight R5 overlays, before UI."""
from pathlib import Path
import sys
root = Path(sys.argv[1]).resolve()
source = Path(__file__).resolve().parent
changes = {}
def edit(path, old, new):
    s = changes.get(path, (root/path).read_text(encoding='utf-8'))
    if s.count(old) != 1:
        raise RuntimeError(f'{path}: expected one R6 shader anchor, got {s.count(old)}: {old[:100]}')
    changes[path] = s.replace(old,new)
h = 'src/mods/vr/d3d12/DIBRPreview.hpp'
c = 'src/mods/vr/d3d12/DIBRPreview.cpp'
d = 'src/mods/vr/D3D12Component.cpp'
edit(h, '        std::array<float, 4> depth_uv_scale_bias{};', '''        std::array<float, 4> depth_uv_scale_bias{};
        uint32_t inspector_view{};
        uint32_t depth_sampling_mode{};
        uint32_t depth_repair_mode{};
        bool preserve_stereo_strength{true};
        float depth_scale{1.0f};
        float depth_display_gain{10.0f};
        float depth_repair_threshold{0.005f};''')
edit(h, '        float padding[16]{};', '''        uint32_t inspector_view{};
        uint32_t depth_sampling_mode{};
        uint32_t depth_repair_mode{};
        uint32_t preserve_stereo_strength{};
        float depth_scale{};
        float depth_display_gain{};
        float depth_repair_threshold{};
        float inspector_reserved{};
        float padding[8]{};''')
edit(c, '    float4 DepthUvScaleBias;\n};', '''    float4 DepthUvScaleBias;
    uint InspectorView;
    uint DepthSamplingMode;
    uint DepthRepairMode;
    uint PreserveStereoStrength;
    float DepthScaleCalibration;
    float DepthDisplayGain;
    float DepthRepairThreshold;
    float InspectorReserved;
};''')
old = '''float ReadDepth(float2 uv) {
    const float2 scale = DepthUvScaleBias.x > 0 && DepthUvScaleBias.y > 0 ?
        DepthUvScaleBias.xy : float2(DepthIsDoubleWide != 0 ? 0.5f : 1.0f, 1.0f);
    const float2 bias = DepthUvScaleBias.x > 0 ? DepthUvScaleBias.zw : float2(0,0);
    const float2 half_texel = 0.5f / float2(DepthWidth, DepthHeight);
    return SourceDepth.SampleLevel(LinearClamp, clamp(saturate(uv) * scale + bias,
        bias + half_texel, bias + scale - half_texel), 0);
}'''
edit(c,old,(source/'InspectorDepth.hlsl').read_text())
# Insert inspection after the inverse solver, before legacy repair helpers.
anchor = 'bool IsFartherDepth(float candidate, float near_depth, float tolerance) {'
edit(c,anchor,'''float4 InspectDepth(float2 uv) {
    const float raw = RawPointDepth(uv);
    const float readable = ReadableDepth(raw);
    if (InspectorView == 1) return float4(raw, raw, raw, 1);
    if (InspectorView == 2) return float4(readable, readable, readable, 1);
    const float2 texel = 1.0f / (float2(DepthWidth, DepthHeight) * DepthScale());
    const float gradient = max(abs(raw - RawPointDepth(uv + float2(texel.x,0))),
                               abs(raw - RawPointDepth(uv + float2(0,texel.y))));
    const float edge = saturate(gradient / max(DepthRepairThreshold, 0.00001f));
    if (InspectorView == 3) return float4(edge,edge,edge,1);
    if (InspectorView == 4) {
        const float3 color = SourceColor.SampleLevel(LinearClamp, uv, 0).rgb;
        return float4(lerp(color, float3(readable,edge,1-readable),0.55f),1);
    }
    uint clamped = 0;
    const float disparity = DisparityPixels * LegacyDepthResponse(saturate(ReadDepth(uv))) /
        max((float)SourceEyeWidth,1.0f);
    const float2 source = ResolveSyntheticRightSourceUv(uv,disparity,TrueReprojectionStrength,clamped);
    const float2 projected = ReprojectSourceUv(source,saturate(ReadDepth(source)),TrueReprojectionStrength);
    const float residual = UseTrueReprojection != 0 ?
        length((projected-uv)*float2(SourceEyeWidth,OutputHeight)) : 0;
    // This is inverse-solve confidence, not a visibility buffer or a hole mask.
    const float uncertainty = clamped != 0 ? 1.0f : saturate(residual / 3.0f);
    return float4(uncertainty,1.0f-uncertainty,0,1);
}

''' + anchor)
edit(c, '    const float2 target_uv = float2(target_u, v);', '''    const float2 target_uv = float2(target_u, v);
    if (InspectorView != 0) {
        Output[dispatch_id.xy] = InspectDepth(target_uv);
        return;
    }''')
# Defense in shader as well as CPU: bypass all saved local-flattening flags.
for old,new in [
('EnableUiFootprintReprojection != 0 ? ui_footprint_mask : 0.0f','EnableUiFootprintReprojection != 0 && PreserveStereoStrength == 0 ? ui_footprint_mask : 0.0f'),
('if (target_right && EnableDepthEdgeStabilization != 0)', 'if (target_right && EnableDepthEdgeStabilization != 0 && PreserveStereoStrength == 0)'),
('if (EnableSpatialRepair != 0 && (target_right || ShowSpatialRepairMask != 0))', 'if (EnableSpatialRepair != 0 && PreserveStereoStrength == 0 && (target_right || ShowSpatialRepairMask != 0))'),
('if (target_right && ui_edge_mask > 0.0f)', 'if (target_right && ui_edge_mask > 0.0f && PreserveStereoStrength == 0)')]: edit(c,old,new)
edit(c, '    constants.reversed_depth = parameters.reversed_depth ? 1 : 0;', '''    constants.inspector_view = std::min(parameters.inspector_view, 5u);
    constants.depth_sampling_mode = std::min(parameters.depth_sampling_mode, 2u);
    constants.depth_repair_mode = std::min(parameters.depth_repair_mode, 1u);
    constants.preserve_stereo_strength = parameters.preserve_stereo_strength ? 1u : 0u;
    constants.depth_scale = std::clamp(parameters.depth_scale, 0.25f, 4.0f);
    constants.depth_display_gain = std::clamp(parameters.depth_display_gain, -8.0f, 24.0f);
    constants.depth_repair_threshold = std::clamp(parameters.depth_repair_threshold, 0.0001f, 0.1f);
    constants.reversed_depth = parameters.reversed_depth ? 1 : 0;''')
edit(d, '    if (m_stock_dibr_scope) parameters.depth_uv_scale_bias = m_stock_dibr_depth->sample_uv();', '''    if (m_stock_dibr_scope) {
        parameters.depth_uv_scale_bias = m_stock_dibr_depth->sample_uv();
        parameters.inspector_view = vr->get_dibr_inspector_view();
        parameters.depth_sampling_mode = vr->get_dibr_depth_sampling_mode();
        parameters.depth_repair_mode = vr->get_dibr_depth_repair_mode();
        parameters.preserve_stereo_strength = vr->is_dibr_preserve_stereo_strength();
        parameters.depth_scale = vr->get_dibr_depth_scale();
        parameters.depth_display_gain = vr->get_dibr_depth_display_gain();
        parameters.depth_repair_threshold = vr->get_dibr_depth_repair_threshold();
    } else {
        // Preserve the original behavior in every unrelated DIBR scope.
        parameters.depth_sampling_mode = 0;
        parameters.preserve_stereo_strength = false;
    }
    if (parameters.preserve_stereo_strength) {
        parameters.depth_edge_stabilization = false;
        parameters.spatial_repair = false;
        parameters.show_spatial_repair_mask = false;
        parameters.ui_edge_guard = false;
        parameters.show_ui_edge_guard_mask = false;
        parameters.ui_footprint_reprojection = false;
        parameters.show_ui_footprint_reprojection_mask = false;
    }''')
# All anchors validated before applying source edits.
for path,s in changes.items(): (root/path).write_text(s,encoding='utf-8')
(root/'src/mods/vr/d3d12/CandidatePolicy.hpp').write_bytes((source/'CandidatePolicy.hpp').read_bytes())
(root/'src/mods/vr/d3d12/StockDibrDepth.hpp').write_bytes((source/'StockDibrDepth.hpp').read_bytes())
print('Applied R6 bounded depth sampling, inspector, calibration, optional spike repair and strength preservation')
