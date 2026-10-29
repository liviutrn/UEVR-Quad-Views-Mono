"""CI71: opt-in LEFT anchored mode-5 spatial reconstruction.
Apply ONLY after CI70, before shader bytecode generation and GPU tests.
"""
from pathlib import Path
import sys

def edit(p,a,b):
 s=p.read_text(encoding="utf-8")
 if s.count(a)!=1:raise RuntimeError("CI71 exact source anchor mismatch: "+str(p)+" "+a[:70])
 p.write_text(s.replace(a,b,1),encoding="utf-8")
def run(root):
 vr=Path(root)/"src/mods/vr";sh=vr/"DuoViewSurfaceReproject.hlsl"
 edit(sh,"    const uint cellsX=MeshConfig.x-1;\n    const uint cell=vertexId/6,corner=vertexId%6;\n    const int2 base=ActiveDepthMin(MeshDepthRect())+int2(cell%cellsX,cell/cellsX);",
 """    const uint cellsX=MeshConfig.x-1;
    const uint cell=vertexId/6,corner=vertexId%6;
    // A/B opt-in: forward-project the entire LEFT source on a 2-pixel
    // grid. Preserve native projection/camera baseline and true metric Z.
    const uint stride=(MeshConfig.w&8u)!=0u ? 2u : 1u;
    const int2 base=ActiveDepthMin(MeshDepthRect())+
        int2(cell%cellsX,cell/cellsX)*int(stride);""")
 edit(sh,"if(MeshConfig.z!=0 && (MeshConfig.w&2u)!=0) {",
         "if(MeshConfig.z!=0 && (MeshConfig.w&2u)!=0 && (MeshConfig.w&8u)==0) {")
 edit(sh,"    const int2 offsets[6]={int2(0,0),int2(1,0),int2(0,1),int2(1,0),int2(1,1),int2(0,1)};",
 """    const int step=int(stride);
    const int2 offsets[6]={int2(0,0),int2(step,0),int2(0,step),
                           int2(step,0),int2(step,step),int2(0,step)};""")
 edit(sh,"        if(!MeshPoint(base+offsets[tri+k],points[k],uvs[k],ws[k]))return o;",
 """        if(!MeshPoint(clamp(base+offsets[tri+k],ActiveDepthMin(MeshDepthRect()),
                    ActiveDepthMax(MeshDepthRect())),points[k],uvs[k],ws[k]))return o;""")
 edit(sh,"    bool allOcclude=true;\n    [unroll] for(int y=0;y<2;++y)",
         "    bool allOcclude=true;\n    uint strongOccluders=0;\n    [unroll] for(int y=0;y<2;++y)")
 edit(sh,"        if(hybrid && occludes)return true;\n        allOcclude=allOcclude && occludes;\n    }\n    return !hybrid && allOcclude;",
 """        if(hybrid && (MeshConfig.w&8u)==0u && occludes)return true;
        strongOccluders+=occludes?1u:0u;
        allOcclude=allOcclude && occludes;
    }
    // A single unstable low-res RIGHT texel cannot erase a high-res
    // LEFT silhouette. Require 3 of 4 proven closer target depths.
    return hybrid ? strongOccluders>=3u : allOcclude;""")
 edit(sh,"""    // Never average foreground and background into a non-existent surface.
    if(any(zs<=0) || farthest-nearest>MeshQuality.x+MeshQuality.y*nearest)return o;
    const float d=lerp(lerp(depths.x,depths.y,fraction.x),lerp(depths.z,depths.w,fraction.x),fraction.y);
    const float nd=(d-DepthViewportRanges.z)/(DepthViewportRanges.w-DepthViewportRanges.z);""",
 """    // Physically correct edge-aware upsampling. Never interpolate depth
    // ACROSS unrelated surfaces, including under reversed-Z.
    if(any(zs<=0))return o;
    const float tolerance=MeshQuality.x+MeshQuality.y*nearest;
    const float4 weights=float4((1-fraction.x)*(1-fraction.y),fraction.x*(1-fraction.y),
                                (1-fraction.x)*fraction.y,fraction.x*fraction.y);
    float4 supported=float4(1,1,1,1);
    if(farthest-nearest>tolerance) {
        if(MeshQuality.w<=1.5f)return o; // legacy A/B baseline
        const float4 nearMembers=float4(abs(zs.x-nearest)<=tolerance,
            abs(zs.y-nearest)<=tolerance,abs(zs.z-nearest)<=tolerance,
            abs(zs.w-nearest)<=tolerance);
        const float4 farMembers=float4(abs(zs.x-farthest)<=tolerance,
            abs(zs.y-farthest)<=tolerance,abs(zs.z-farthest)<=tolerance,
            abs(zs.w-farthest)<=tolerance);
        const float nearCount=dot(nearMembers,float4(1,1,1,1));
        const float farCount=dot(farMembers,float4(1,1,1,1));
        if(nearCount>=3.f && farCount<3.f)supported=nearMembers;
        else if(farCount>=3.f && nearCount<3.f)supported=farMembers;
        else return o; // unresolved silhouette: no fake intermediate depth
    }
    const float4 coeff=weights*supported;
    const float norm=dot(coeff,float4(1,1,1,1));
    if(norm<1.e-5f)return o;
    const float d=dot(coeff,depths)/norm;
    const float nd=(d-DepthViewportRanges.z)/(DepthViewportRanges.w-DepthViewportRanges.z);""")
 h=vr/"DuoViewD3D12.hpp"
 edit(h,"            c.mesh_config[0]=UINT(columns);c.mesh_config[1]=UINT(rows);\n            c.mesh_config[2]=pass==0?1u:0u;",
 """            const bool left_anchored=pass==0 && quality[3]>1.5f;
            const double stride=left_anchored?2.0:1.0;
            c.mesh_config[0]=UINT(std::ceil((columns-1.0)/stride)+1.0);
            c.mesh_config[1]=UINT(std::ceil((rows-1.0)/stride)+1.0);
            c.mesh_config[2]=pass==0?1u:0u;""")
 edit(h,"            if(g.reverse_depth)c.mesh_config[3]|=4u;",
        "            if(g.reverse_depth)c.mesh_config[3]|=4u;\n            if(left_anchored)c.mesh_config[3]|=8u;")
 h=Path(root)/"src/mods/VR.hpp"
 edit(h,"    bool duoview_foreground_refinement_enabled() const { return m_duo_foreground_refinement->value(); }",
 """    bool duoview_foreground_refinement_enabled() const { return m_duo_foreground_refinement->value(); }
    bool duoview_left_anchored_mode() const { return m_duo_left_anchor->value(); }""")
 edit(h,'    const ModToggle::Ptr m_duo_foreground_refinement{ModToggle::create(generate_name("DuoViewForegroundRefinement"), true)};',
 '''    const ModToggle::Ptr m_duo_foreground_refinement{ModToggle::create(generate_name("DuoViewForegroundRefinement"), true)};
    const ModToggle::Ptr m_duo_left_anchor{ModToggle::create(generate_name("DuoViewLeftAnchoredReprojection"), true)};''')
 edit(h,"            *m_duo_foreground_refinement, *m_duo_visibility_absolute, *m_duo_visibility_relative_percent, *m_duo_foreground_edge_radius,",
         "            *m_duo_foreground_refinement, *m_duo_left_anchor, *m_duo_visibility_absolute, *m_duo_visibility_relative_percent, *m_duo_foreground_edge_radius,")
 h=Path(root)/"src/mods/VR.cpp"
 edit(h,"                    m_duo_foreground_refinement->value()=true;",
         "                    m_duo_foreground_refinement->value()=true;\n                    m_duo_left_anchor->value()=true;")
 edit(h,'                m_duo_foreground_refinement->draw("Preserve fine foreground (extra GPU work)");',
 '''                m_duo_left_anchor->draw("Mode 5: LEFT-anchored edge stabilization (GPU cost)");
                ImGui::TextWrapped("ON: high-res LEFT geometry forward mesh at 2-pixel stride, RIGHT-depth edge-aware upsampling and 3/4 occlusion consensus. OFF: original mode 5 for A/B. Native disparity unchanged; no untracked temporal depth smoothing.");
                m_duo_foreground_refinement->draw("Preserve fine foreground (extra GPU work)");''')
 h=vr/"D3D12Component.cpp"
 edit(h,"                                vr->duoview_foreground_edge_radius(),vr->duoview_foreground_refinement_enabled()?1.f:0.f};",
 """                                vr->duoview_foreground_edge_radius(),
                                vr->duoview_left_anchored_mode()?2.f:
                                    (vr->duoview_foreground_refinement_enabled()?1.f:0.f)};""")
 print("CI71: high-resolution LEFT-anchored mode-5, edge vote and option applied")
if __name__=="__main__":
 if len(sys.argv)!=2:raise SystemExit("usage: ci71/apply.py backend")
 run(Path(sys.argv[1]).resolve())
