#!/usr/bin/env python3
"""Build3: preserve the exact R5 synthesis, add optional reverse-origin eye.
The Joey R5 left-origin path remains bytewise equivalent for normal methods 3/4.
"""
import pathlib,sys
root=pathlib.Path(sys.argv[1]).resolve()
def edit(path,old,new):
 p=root/path;s=p.read_text(encoding='utf-8-sig')
 if s.count(old)!=1:raise RuntimeError(f'reverse R5 anchor mismatch {path}: {s.count(old)} {old[:110]!r}')
 p.write_text(s.replace(old,new,1),encoding='utf-8',newline='')
h='src/mods/vr/d3d12/DIBRPreview.hpp'
c='src/mods/vr/d3d12/DIBRPreview.cpp'
edit(h,'        std::array<float, 4> depth_uv_scale_bias{};',
'''        std::array<float, 4> depth_uv_scale_bias{};
        // Only the second DuoView R5 invocation uses source RIGHT -> synthetic LEFT.
        bool right_eye_source{};''')
edit(h,'        float depth_rect_alignment{};',
'''        uint32_t reverse_source_eye{};''')
edit(c,'    float UiFootprintReprojectionStrength;\n    float4 DepthUvScaleBias;',
'''    float UiFootprintReprojectionStrength;
    uint ReverseSourceEye;
    float4 DepthUvScaleBias;''')
edit(c,'    constants.reversed_depth = parameters.reversed_depth ? 1 : 0;',
'''    constants.reverse_source_eye = parameters.right_eye_source ? 1u : 0u;
    constants.reversed_depth = parameters.reversed_depth ? 1 : 0;''')
edit(c,'    const float disparity_uv = (DisparityPixels * LegacyDepthResponse(raw_depth) * edge) / (float)SourceEyeWidth;',
'''    const bool synthesized_eye = target_right != (ReverseSourceEye != 0);
    const float disparity_uv = (DisparityPixels * LegacyDepthResponse(raw_depth) * edge) /
        (float)SourceEyeWidth * (ReverseSourceEye != 0 ? -1.0f : 1.0f);''')
edit(c,'(target_right || ShowUiFootprintReprojectionMask != 0) ?',
       '(synthesized_eye || ShowUiFootprintReprojectionMask != 0) ?')
edit(c,'    if (target_right || (EnableSpatialRepair != 0 && ShowSpatialRepairMask != 0)) {',
       '    if (synthesized_eye || (EnableSpatialRepair != 0 && ShowSpatialRepairMask != 0)) {')
edit(c,'    float2 source_uv = target_right ? synthesized_source_uv : target_uv;',
       '    float2 source_uv = synthesized_eye ? synthesized_source_uv : target_uv;')
edit(c,'    if (target_right && EnableDepthEdgeStabilization != 0) {',
       '    if (synthesized_eye && EnableDepthEdgeStabilization != 0) {')
edit(c,'    if (EnableSpatialRepair != 0 && (target_right || ShowSpatialRepairMask != 0)) {',
       '    if (EnableSpatialRepair != 0 && (synthesized_eye || ShowSpatialRepairMask != 0)) {')
edit(c,'    if (target_right && repair_state == 2u) {',
       '    if (synthesized_eye && repair_state == 2u) {')
edit(c,'    const float ui_edge_mask = (target_right || ShowUiEdgeGuardMask != 0) ?',
       '    const float ui_edge_mask = (synthesized_eye || ShowUiEdgeGuardMask != 0) ?')
edit(c,'    if (target_right && ui_edge_mask > 0.0f) {',
       '    if (synthesized_eye && ui_edge_mask > 0.0f) {')
print('R5 bidirectional pass: left->right unchanged, right->left reverse source and projection matrix option ready.')
