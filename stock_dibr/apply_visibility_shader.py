"""R7 forward visibility shader and parameters, after both R6 stages."""
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve();here=Path(__file__).resolve().parent
changes={}
def edit(path,old,new):
    s=changes.get(path,(root/path).read_text(encoding='utf-8'))
    if s.count(old)!=1: raise RuntimeError(f'{path}: R7 shader anchor count {s.count(old)}: {old[:100]}')
    changes[path]=s.replace(old,new)
h='src/mods/vr/d3d12/DIBRPreview.hpp';c='src/mods/vr/d3d12/DIBRPreview.cpp';d='src/mods/vr/D3D12Component.cpp'
edit(h,'        float depth_repair_threshold{0.005f};','''        float depth_repair_threshold{0.005f};
        uint32_t reconstruction_mode{};
        uint32_t visibility_fill_radius{32};
        float visibility_depth_tolerance{0.03f};''')
edit(h,'''        float inspector_reserved{};
        float padding[8]{};''','''        uint32_t reconstruction_mode{};
        uint32_t visibility_fill_radius{};
        float visibility_depth_tolerance{};
        float padding[6]{};''')
edit(c,'    float InspectorReserved;','''    uint ReconstructionMode;
    uint VisibilityFillRadius;
    float VisibilityDepthTolerance;''')
edit(c,'RWTexture2D<float4> Output : register(u0);','''RWTexture2D<float4> Output : register(u0);
RWTexture2D<uint> VisibilityDepth : register(u1);
RWTexture2D<uint> VisibilitySource : register(u2);''')
edit(c,'''float ReadDepth(float2 uv) {
    float value = SampleSelectedDepth(uv);''','''float CalibrateAndRepairDepth(float2 uv, float value) {''')
edit(c,'float ReadableDepth(float value) {','''float ReadDepth(float2 uv) { return CalibrateAndRepairDepth(uv,SampleSelectedDepth(uv)); }
float ReadableDepth(float value) {''')
edit(c,'bool IsFartherDepth(float candidate, float near_depth, float tolerance) {',
    ')DIBR"\nR"DIBR(\n'+(here/'VisibilityWarp.hlsl').read_text()+'\n)DIBR"\nR"DIBR(\nbool IsFartherDepth(float candidate, float near_depth, float tolerance) {')
edit(c,'''    if (InspectorView != 0) {
        Output[dispatch_id.xy] = InspectDepth(target_uv);
        return;
    }''','''    if (ReconstructionMode != 0 && UseTrueReprojection != 0 && (InspectorView == 0 || InspectorView == 6)) {
        if (InspectorView == 0 && !target_right) {
            float4 left_color=SourceColor.SampleLevel(LinearClamp,target_uv,0);
            left_color.a=1;
            Output[dispatch_id.xy]=left_color;
            return;
        }
        uint state;
        float4 right_color=VisibilityResolve(target_uv,state);
        float4 color=InspectorView == 6 ? VisibilityStateColor(state) :
            (target_right ? right_color : SourceColor.SampleLevel(LinearClamp,target_uv,0));
        color.a=1;
        Output[dispatch_id.xy]=color;
        return;
    }
    if (InspectorView != 0) {
        Output[dispatch_id.xy] = InspectorView == 6 ? float4(.7f,.1f,.7f,1) : InspectDepth(target_uv);
        return;
    }''')
edit(c,'    constants.inspector_view = (std::min)(parameters.inspector_view, 5u);','''    constants.inspector_view = (std::min)(parameters.inspector_view, 6u);
    constants.reconstruction_mode = parameters.reconstruction_mode != 0 ? 1u : 0u;
    constants.visibility_fill_radius = (std::min)(parameters.visibility_fill_radius, 64u);
    constants.visibility_depth_tolerance = std::clamp(parameters.visibility_depth_tolerance, 0.001f, 0.25f);''')
edit(d,'        parameters.depth_repair_threshold = vr->get_dibr_depth_repair_threshold();','''        parameters.depth_repair_threshold = vr->get_dibr_depth_repair_threshold();
        parameters.reconstruction_mode = vr->get_dibr_reconstruction_mode();
        parameters.visibility_fill_radius = vr->get_dibr_visibility_fill_radius();
        parameters.visibility_depth_tolerance = vr->get_dibr_visibility_depth_tolerance();''')
for path,s in changes.items(): (root/path).write_text(s,encoding='utf-8')
print('Applied R7 point-forward visibility, explicit coverage and bounded background reconstruction')
