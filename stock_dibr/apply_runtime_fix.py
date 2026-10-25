"""Address first headset-test failures after the base and hook overlays."""
import pathlib, sys
root=pathlib.Path(sys.argv[1]).resolve()
def edit(path, old, new):
    p=root/path;s=p.read_text()
    if s.count(old)!=1: raise RuntimeError(f'{path}: {s.count(old)} matches for {old[:90]}')
    p.write_text(s.replace(old,new))
dc='src/mods/vr/D3D12Component.cpp'
# Preserve the original engine stereo during warmup: it already contains two
# correctly projected eye images. Duplicating its left eye with two different
# OpenXR FOVs was the demonstrated right-eye misalignment.
edit(dc,'''if (m_stock_dibr_scope && vr->is_dibr_single_view_requested() && !dibr_preview_succeeded) {''',
    '''if (m_stock_dibr_scope && vr->is_dibr_single_view_projection_configured() && !dibr_preview_succeeded) {''')
edit(dc,'''    if (parameters.spatial_repair) {''','''    if (m_stock_dibr_scope) parameters.depth_uv_scale_bias = m_stock_dibr_depth.sample_uv();
    if (parameters.spatial_repair) {''')
h='src/mods/vr/d3d12/DIBRPreview.hpp';cpp='src/mods/vr/d3d12/DIBRPreview.cpp'
edit(cpp,'''DXGI_FORMAT DIBRPreview::depth_srv_format(DXGI_FORMAT format) {
    switch (format) {''','''DXGI_FORMAT DIBRPreview::depth_srv_format(DXGI_FORMAT format) {
    switch (format) {
    case DXGI_FORMAT_R32G8X24_TYPELESS:
    case DXGI_FORMAT_D32_FLOAT_S8X24_UINT:
        return DXGI_FORMAT_R32_FLOAT_X8X24_TYPELESS;''')
edit(cpp,'''    auto destination_desc = source_desc;
    // The source may be a two-eye texture array.''','''    auto destination_desc = source_desc;
    if (destination_desc.Format == DXGI_FORMAT_D32_FLOAT_S8X24_UINT)
        destination_desc.Format = DXGI_FORMAT_R32G8X24_TYPELESS;
    // The source may be a two-eye texture array.''')
edit(h,'    struct Parameters {','    struct Parameters {\n        std::array<float, 4> depth_uv_scale_bias{};')
edit(h,'        float padding[21]{};','''        float depth_rect_alignment{};
        float depth_uv_scale_bias[4]{};
        float padding[16]{};''')
edit(h,'bool validate_inputs(ID3D12Resource* color, ID3D12Resource* depth, std::string& reason) const;',
    'bool validate_inputs(ID3D12Resource* color, ID3D12Resource* depth, const Parameters& parameters, std::string& reason) const;')
edit(cpp,'bool DIBRPreview::validate_inputs(ID3D12Resource* color, ID3D12Resource* depth, std::string& reason) const {',
    'bool DIBRPreview::validate_inputs(ID3D12Resource* color, ID3D12Resource* depth, const Parameters& parameters, std::string& reason) const {')
edit(cpp,'!validate_inputs(color, depth, validation_reason)', '!validate_inputs(color, depth, parameters, validation_reason)')
edit(cpp,'''    if (stock_dibr::layout(depth_desc.Width, depth_desc.Height, color_desc.Width, color_desc.Height) == stock_dibr::Layout::Invalid) {''','''    const auto& uv = parameters.depth_uv_scale_bias;
    const bool has_rect = uv[0] != 0 || uv[1] != 0 || uv[2] != 0 || uv[3] != 0;
    if (has_rect) {
        for (const auto v : uv) if (!std::isfinite(v)) { reason = "nonfinite depth viewport"; return false; }
        if (uv[0] <= 0 || uv[1] <= 0 || uv[2] < 0 || uv[3] < 0 ||
            uv[0] + uv[2] > 1.00001f || uv[1] + uv[3] > 1.00001f ||
            stock_dibr::layout(static_cast<uint64_t>(std::lround(depth_desc.Width * uv[0])),
                static_cast<uint32_t>(std::lround(depth_desc.Height * uv[1])),
                color_desc.Width, color_desc.Height) != stock_dibr::Layout::Eye) {
            reason = "depth viewport does not match the scene eye"; return false;
        }
    }
    if (!has_rect && stock_dibr::layout(depth_desc.Width, depth_desc.Height, color_desc.Width, color_desc.Height) == stock_dibr::Layout::Invalid) {''')
edit(cpp,'#include <cstdio>','#include <cstdio>\n#include <cmath>')
edit(cpp,'    float UiFootprintReprojectionStrength;','    float UiFootprintReprojectionStrength;\n    float4 DepthUvScaleBias;')
edit(cpp,'''    const float max_u = DepthIsDoubleWide != 0 ? 0.5f : 1.0f;
    const float2 half_texel = 0.5f / float2(DepthWidth, DepthHeight);
    const float2 mapped = float2(saturate(uv.x) * max_u, saturate(uv.y));
    return SourceDepth.SampleLevel(LinearClamp, clamp(mapped, half_texel,
        float2(max_u, 1.0f) - half_texel), 0);''','''    const float2 scale = DepthUvScaleBias.x > 0 && DepthUvScaleBias.y > 0 ?
        DepthUvScaleBias.xy : float2(DepthIsDoubleWide != 0 ? 0.5f : 1.0f, 1.0f);
    const float2 bias = DepthUvScaleBias.x > 0 ? DepthUvScaleBias.zw : float2(0,0);
    const float2 half_texel = 0.5f / float2(DepthWidth, DepthHeight);
    return SourceDepth.SampleLevel(LinearClamp, clamp(saturate(uv) * scale + bias,
        bias + half_texel, bias + scale - half_texel), 0);''')
edit(cpp,'''    const float2 texel = float2(DepthIsDoubleWide != 0 ? 2.0f : 1.0f, 1.0f) /
        float2((float)DepthWidth, (float)DepthHeight);''','''    const float2 scale = DepthUvScaleBias.x > 0 && DepthUvScaleBias.y > 0 ?
        DepthUvScaleBias.xy : float2(DepthIsDoubleWide != 0 ? 0.5f : 1.0f, 1.0f);
    const float2 texel = 1.0f / (float2(DepthWidth, DepthHeight) * scale);''')
edit(cpp,'    constants.reversed_depth = parameters.reversed_depth ? 1 : 0;',
    '''    std::memcpy(constants.depth_uv_scale_bias, parameters.depth_uv_scale_bias.data(), sizeof(constants.depth_uv_scale_bias));
    constants.reversed_depth = parameters.reversed_depth ? 1 : 0;''')
edit('src/mods/VR.cpp','''                if (ImGui::TreeNode("DIBR quality tuning")) {''','''                if (std::string_view{m_d3d12.get_dibr_preview_status()} != "ready")
                    ImGui::TextWrapped("DIBR tuning has no effect until live depth capture and synthesis are ready.");
                if (ImGui::TreeNode("DIBR quality tuning")) {''')
print('Applied headset-test correction: warmup stereo, explicit depth viewport, active tuning explanation')
