#!/usr/bin/env python3
"""M8: depth-aware M4 foveal edge conditioning and disocclusion fill.

Runs after M7 accumulation; no modifications to #265's frame/depth ownership.
With M8 OFF all existing edge penalties and fill positions are unchanged.
Near: crisp/minimum geometric smoothing + strong fill.
Far: stronger geometric smoothing + weak/zero fill.
"""
from pathlib import Path
import sys

def once(text, old, new, context):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"M8 {context}: expected one anchor, got {count}: {old[:96]!r}")
    return text.replace(old, new, 1)

def edit(path, transforms):
    text = path.read_text(encoding="utf-8")
    for context, old, new in transforms:
        text = once(text, old, new, context)
    path.write_text(text, encoding="utf-8")


def uniformize_lane_loops(block):
    """FXC requires all lanes to take the same loop trip count before a group barrier."""
    token = "for (uint x=lane; x<w; x+=128)"
    offset = 0
    count = 0
    while True:
        pos = block.find(token, offset)
        if pos < 0:
            break
        j = pos + len(token)
        while j < len(block) and block[j].isspace():
            j += 1
        if j >= len(block):
            raise RuntimeError("M8 truncated lane loop")
        if block[j] == "{":
            depth, end = 1, j + 1
            while depth > 0:
                if end >= len(block):
                    raise RuntimeError("M8 unbalanced lane loop")
                if block[end] == "{":
                    depth += 1
                elif block[end] == "}":
                    depth -= 1
                end += 1
            body = block[j+1:end-1]
        else:
            end = block.find(";", j)
            if end < 0:
                raise RuntimeError("M8 unterminated lane loop")
            end += 1
            body = block[j:end]
        replacement = ("for (uint tile=0u; tile<(w+127u)/128u; ++tile) {\n"
                       "    const uint x=128u*tile+lane;\n"
                       "    if (x<w) {\n" + body + "\n    }\n}")
        block = block[:pos] + replacement + block[end:]
        offset = pos + len(replacement)
        count += 1
    if count < 1:
        raise RuntimeError("M8 expected at least one lane loop")
    return block

def shaders(sh):
    p = sh / "DuoViewM1Stereo.hlsl"
    text = p.read_text(encoding="utf-8")
    text = once(text,
        "    float4 M7Controls;\n    uint4 M7ColorExtent;\n    float4 M5Sharpen;",
        "    float4 M7Controls;\n    uint4 M7ColorExtent;\n"
        "    float4 M8Distance; // inverse depth of start,end; enabled\n"
        "    float4 M8Effects;  // near/far smoothing, near/far fill\n"
        "    float4 M5Sharpen;", "M8 shader constants")
    anchor = "// Fine NGX depth is sampled only during conditioning"
    helpers = r"""// All depths passed here are inverse *engine* units from M4, not metres.
// The CPU converts the user-specified distance thresholds using world_to_meters.
float M8FarWeight(float inverseDepth) {
    if (M8Distance.z < .5) return 0.;
    const float span=max(M8Distance.x-M8Distance.y,1.e-8);
    const float t=saturate((M8Distance.x-inverseDepth)/span);
    return t*t*(3.-2.*t);
}
float M8AdjustedPenalty(float inverseDepth, float original) {
    if (M8Distance.z < .5) return original;
    const float smoothness=lerp(M8Effects.x,M8Effects.y,M8FarWeight(inverseDepth));
    // Larger penalty => narrower/sharper envelope, smaller => broader/softer.
    const float proposed=original*lerp(2.0,.35,saturate(smoothness));
    // Never make k*dD/du steeper than the warp's no-fold bound.
    const float kmax=max(max(abs(M1Eye.x),abs(M1Eye.y)),.00001);
    const float maxSafe=.95/max(kmax*float(M4Grid.x),.00001);
    return min(proposed,maxSafe);
}
float M8FillStrength(float inverseDepth) {
    if (M8Distance.z < .5) return 1.;
    return saturate(lerp(M8Effects.z,M8Effects.w,M8FarWeight(inverseDepth)));
}

// Fine NGX depth is sampled only during conditioning""";
    text=once(text,anchor,helpers,"M8 helper insertion")
    text=once(text,
        "groupshared float M1Next[1024];",
        "groupshared float M1Next[1024];\n"
        "groupshared float M8Origin[1024];\n"
        "groupshared float M8NextOrigin[1024];",
        "M8 seed-origin history for stable cone slopes")

    start=text.index("void M4Envelope(")
    end=text.index("[numthreads(128,1,1)]",start)
    block=text[start:end]
    block=once(block,
      "const float pmin=ps>0.0 ? min(pf,ps) : pf;",
      "const float pmin=(ps>0.0 ? min(pf,ps) : pf)*(M8Distance.z>.5 ? .35 : 1.);",
      "one-sided envelope iteration limit")
    block=once(block,
      "M1Row[xf]-float(step)*pf",
      "M1Row[xf]-float(step)*M8AdjustedPenalty(M8Distance.z>.5 ? M8Origin[xf] : M1Row[xf],pf)",
      "one-sided foreground edge")
    block=once(block,
      "M1Row[xs]-float(step)*ps",
      "M1Row[xs]-float(step)*M8AdjustedPenalty(M8Distance.z>.5 ? M8Origin[xs] : M1Row[xs],ps)",
      "one-sided background edge")
    block=once(block,
      """            float v=M1Row[x];
            if (xf>=0 && xf<int(w)) v=max(v,M1Row[xf]-float(step)*M8AdjustedPenalty(M8Distance.z>.5 ? M8Origin[xf] : M1Row[xf],pf));
            if (ps>0.0 && xs>=0 && xs<int(w)) v=max(v,M1Row[xs]-float(step)*M8AdjustedPenalty(M8Distance.z>.5 ? M8Origin[xs] : M1Row[xs],ps));
            M1Next[x]=v;""",
      """            float v=M1Row[x], origin=0.;
            if (M8Distance.z>.5) origin=M8Origin[x];
            if (xf>=0 && xf<int(w)) {
                const float candidate=M1Row[xf]-float(step)*M8AdjustedPenalty(M8Distance.z>.5 ? M8Origin[xf] : M1Row[xf],pf);
                if (candidate>v) { v=candidate; if (M8Distance.z>.5) origin=M8Origin[xf]; }
            }
            if (ps>0.0 && xs>=0 && xs<int(w)) {
                const float candidate=M1Row[xs]-float(step)*M8AdjustedPenalty(M8Distance.z>.5 ? M8Origin[xs] : M1Row[xs],ps);
                if (candidate>v) { v=candidate; if (M8Distance.z>.5) origin=M8Origin[xs]; }
            }
            M1Next[x]=v;
            if (M8Distance.z>.5) M8NextOrigin[x]=origin;""",
      "one-sided preserve original depth of winning contributor")
    block=once(block,
      "for (uint x=lane; x<w; x+=128) M1Row[x]=M1Next[x];",
      """for (uint x=lane; x<w; x+=128) {
            M1Row[x]=M1Next[x];
            if (M8Distance.z>.5) M8Origin[x]=M8NextOrigin[x];
        }""",
      "one-sided carry origin between doubling passes")
    block=uniformize_lane_loops(block)
    text=text[:start]+block+text[end:]

    start=text.index("void CSConditionM4(")
    end=text.index("void CSConditionM4Vertical(",start)
    block=text[start:end]
    block=once(block,
      "float(step-1)*pen<limit",
      "float(step-1)*pen*(M8Distance.z>.5 ? .35 : 1.)<limit",
      "symmetric iteration limit")
    block=once(block,
      "M1Row[x-step]-penalty",
      "M1Row[x-step]-float(step)*M8AdjustedPenalty(M8Distance.z>.5 ? M8Origin[x-step] : M1Row[x-step],pen)",
      "symmetric left contribution")
    block=once(block,
      "M1Row[x+step]-penalty",
      "M1Row[x+step]-float(step)*M8AdjustedPenalty(M8Distance.z>.5 ? M8Origin[x+step] : M1Row[x+step],pen)",
      "symmetric right contribution")
    block=once(block,
      """const float l=x>=step ? M1Row[x-step]-float(step)*M8AdjustedPenalty(M8Distance.z>.5 ? M8Origin[x-step] : M1Row[x-step],pen) : 0.0;
                const float r=x+step<w ? M1Row[x+step]-float(step)*M8AdjustedPenalty(M8Distance.z>.5 ? M8Origin[x+step] : M1Row[x+step],pen) : 0.0;""",
      """float l=0.0, r=0.0;
                if (x>=step)
                    l=M1Row[x-step]-float(step)*M8AdjustedPenalty(M8Distance.z>.5 ? M8Origin[x-step] : M1Row[x-step],pen);
                if (x+step<w)
                    r=M1Row[x+step]-float(step)*M8AdjustedPenalty(M8Distance.z>.5 ? M8Origin[x+step] : M1Row[x+step],pen);""",
      "never read group-shared origins outside the image")
    block=once(block,
       "        M1Row[x]=knee>0.0 ? nearDepth : min(nearDepth,M1Filter.y);",
       """        M1Row[x]=knee>0.0 ? nearDepth : min(nearDepth,M1Filter.y);
        // Initialize source origins within the seed loop; the existing group
        // barrier after this loop publishes both M1Row and M8Origin.
        M8Origin[x]=M1Row[x];""",
       "seed fine-depth source origins before the existing uniform barrier")
    block=once(block,
       "                M1Next[x]=max(M1Row[x],max(l,r));",
       """                const float v=M1Row[x];
                M1Next[x]=max(v,max(l,r));
                if (M8Distance.z>.5) {
                    float origin=M8Origin[x];
                    if (l>v && l>=r) origin=M8Origin[x-step];
                    else if (r>v && r>l) origin=M8Origin[x+step];
                    M8NextOrigin[x]=origin;
                }""",
       "symmetric carry winning source origin")
    block=once(block,
       "for (uint x=lane; x<w; x+=128) M1Row[x]=M1Next[x];",
       """for (uint x=lane; x<w; x+=128) {
                M1Row[x]=M1Next[x];
                if (M8Distance.z>.5) M8Origin[x]=M8NextOrigin[x];
            }""",
       "symmetric carry origin between doubling passes")
    block=once(block,
       "for (uint x=lane; x<w; x+=128) { M1Left[x]=M1Row[x]; M1Row[x]=M1Seed[x]; }",
       """for (uint x=lane; x<w; x+=128) {
            M1Left[x] = M1Row[x]; M1Row[x] = M1Seed[x];
            if (M8Distance.z>.5) M8Origin[x]=M1Seed[x];
        }""",
       "reset origin for right-eye conditioning")
    # FXC X3663: a post-seed group barrier cannot follow a loop whose exit
    # condition depends on SV_GroupIndex. All 128 lanes must take the same
    # number of iterations, even for partial tiles of the last row.
    block=once(block,
       "    for (uint x=lane; x<w; x+=128) {\n        const float2 local=",
       "    for (uint tile=0u; tile<(w+127u)/128u; ++tile) {\n        const uint x=128u*tile+lane;\n        if (x<w) {\n        const float2 local=",
       "uniformize fine-depth seed tile loop before group barrier")
    block=once(block,
       "        M8Origin[x]=M1Row[x];\n    }\n    GroupMemoryBarrierWithGroupSync();",
       "        M8Origin[x]=M1Row[x];\n        }\n    }\n    GroupMemoryBarrierWithGroupSync();",
       "end uniform fine-depth seed tile loop outside varying branch")
    block=uniformize_lane_loops(block)
    text=text[:start]+block+text[end:]

    text=once(text,
        "    if(!(stretch>(M3Flags.z>0. ? M3Flags.z : 2.0))) return root;",
        """    // M8 uses an explicit disocclusion gate even when M3 per-eye edges are OFF.
    const float gate=M8Distance.z>.5 ? 2.0 : (M3Flags.z>0. ? M3Flags.z : 2.0);
    if(!(stretch>gate)) return root;""",
        "M8 rejects non-holes before fill sampling")
    # Preserve the original M7 inCrop/M3 fill eligibility for M8-off parity.
    text=once(text,
        "    if (inCrop && um>M2Crop.x && um<M2Crop.z)\n"
        "        fill=float3(dir,d,1.);\n"
        "    return clamp(um,0.0,1.0);",
        "    // Fill strength follows the occluding foreground, not the uncovered wall.\n"
        "    const float strength=inCrop ? M8FillStrength(max(dl,dr)) : 1.;\n"
        "    if (inCrop && um>M2Crop.x && um<M2Crop.z && strength>.001)\n"
        "        fill=float3(dir,d,strength);\n"
        "    return lerp(root,clamp(um,0.0,1.0),strength);",
        "distance-weighted hole movement and fill metadata")
    p.write_text(text,encoding="utf-8")

    raster=sh/"DuoViewNativeCompositeRaster.hlsl"
    edit(raster,[
      ("M8 allow fractional fill", "fill.z>.5 && (M7Controls.y>0. || M7Controls.z>0.)",
       "fill.z>.001 && (M7Controls.y>0. || M7Controls.z>0. || M8Distance.z>.5)"),
      ("M8 interpolate fill treatment", "            fovea.rgb=filled;",
       "            fovea.rgb=lerp(fovea.rgb,filled,saturate(fill.z));"),
    ])

def backend(mods):
    vr=mods/"vr"
    edit(vr/"DuoViewConfig.hpp",[
      ("M8 option declarations",
       "    float edge_history{.70f}, fill_history{.65f}, fill_blur_px{1.25f};",
       """    float edge_history{.70f}, fill_history{.65f}, fill_blur_px{1.25f};
    bool m8_distance{false}; // OFF preserves M7 output exactly
    float m8_near_m{2.f}, m8_far_m{5.f};
    float m8_edge_near{0.f}, m8_edge_far{1.f};
    float m8_fill_near{1.f}, m8_fill_far{0.f};"""),
      ("M8 validation",
       "        out.fill_blur_px=(std::clamp)(requested.fill_blur_px,0.f,12.f);",
       """        out.fill_blur_px=(std::clamp)(requested.fill_blur_px,0.f,3.f);
    out.m8_distance=requested.m8_distance;
    if(std::isfinite(requested.m8_near_m))
        out.m8_near_m=(std::clamp)(requested.m8_near_m,.25f,50.f);
    if(std::isfinite(requested.m8_far_m))
        out.m8_far_m=(std::clamp)(requested.m8_far_m,.5f,100.f);
    out.m8_far_m=(std::max)(out.m8_far_m,out.m8_near_m+.1f);
    if(std::isfinite(requested.m8_edge_near))
        out.m8_edge_near=(std::clamp)(requested.m8_edge_near,0.f,1.f);
    if(std::isfinite(requested.m8_edge_far))
        out.m8_edge_far=(std::clamp)(requested.m8_edge_far,0.f,1.f);
    if(std::isfinite(requested.m8_fill_near))
        out.m8_fill_near=(std::clamp)(requested.m8_fill_near,0.f,1.f);
    if(std::isfinite(requested.m8_fill_far))
        out.m8_fill_far=(std::clamp)(requested.m8_fill_far,0.f,1.f);"""),
    ])
    edit(mods/"VR.hpp",[
      ("M8 persistent controls",
       "    const ModSlider::Ptr m_duo_fill_blur{ModSlider::create(generate_name(\"DuoFillBlurPixels\"),0.f,3.f,1.25f)};",
       """    const ModSlider::Ptr m_duo_fill_blur{ModSlider::create(generate_name("DuoFillBlurPixels"),0.f,3.f,1.25f)};
    const ModToggle::Ptr m_duo_m8_distance{ModToggle::create(generate_name("DuoM8DistanceEdges"),false)};
    const ModSlider::Ptr m_duo_m8_near_m{ModSlider::create(generate_name("DuoM8StartMeters"),.25f,50.f,2.f)};
    const ModSlider::Ptr m_duo_m8_far_m{ModSlider::create(generate_name("DuoM8EndMeters"),.5f,100.f,5.f)};
    const ModSlider::Ptr m_duo_m8_edge_near{ModSlider::create(generate_name("DuoM8EdgeNear"),0.f,1.f,0.f)};
    const ModSlider::Ptr m_duo_m8_edge_far{ModSlider::create(generate_name("DuoM8EdgeFar"),0.f,1.f,1.f)};
    const ModSlider::Ptr m_duo_m8_fill_near{ModSlider::create(generate_name("DuoM8FillNear"),0.f,1.f,1.f)};
    const ModSlider::Ptr m_duo_m8_fill_far{ModSlider::create(generate_name("DuoM8FillFar"),0.f,1.f,0.f)};"""),
      ("M8 settings persist",
       "*m_duo_edge_history, *m_duo_fill_history, *m_duo_fill_blur,",
       """*m_duo_edge_history, *m_duo_fill_history, *m_duo_fill_blur,
            *m_duo_m8_distance, *m_duo_m8_near_m, *m_duo_m8_far_m,
            *m_duo_m8_edge_near, *m_duo_m8_edge_far, *m_duo_m8_fill_near, *m_duo_m8_fill_far,"""),
    ])
    edit(mods/"VR.cpp",[
      ("M8 reset",
       "                    m_duo_fill_blur->value()=1.25f;",
       """                    m_duo_fill_blur->value()=1.25f;
                    m_duo_m8_distance->value()=false;
                    m_duo_m8_near_m->value()=2.f; m_duo_m8_far_m->value()=5.f;
                    m_duo_m8_edge_near->value()=0.f; m_duo_m8_edge_far->value()=1.f;
                    m_duo_m8_fill_near->value()=1.f; m_duo_m8_fill_far->value()=0.f;"""),
      ("M8 frozen profile",
       "        .fill_blur_px=m_duo_fill_blur->value(),",
       """        .fill_blur_px=m_duo_fill_blur->value(),
        .m8_distance=m_duo_m8_distance->value(),
        .m8_near_m=m_duo_m8_near_m->value(), .m8_far_m=m_duo_m8_far_m->value(),
        .m8_edge_near=m_duo_m8_edge_near->value(), .m8_edge_far=m_duo_m8_edge_far->value(),
        .m8_fill_near=m_duo_m8_fill_near->value(), .m8_fill_far=m_duo_m8_fill_far->value(),"""),
      ("M8 live changes",
       "        current.fill_blur_px==candidate.fill_blur_px &&",
       """        current.fill_blur_px==candidate.fill_blur_px &&
        current.m8_distance==candidate.m8_distance &&
        current.m8_near_m==candidate.m8_near_m && current.m8_far_m==candidate.m8_far_m &&
        current.m8_edge_near==candidate.m8_edge_near && current.m8_edge_far==candidate.m8_edge_far &&
        current.m8_fill_near==candidate.m8_fill_near && current.m8_fill_far==candidate.m8_fill_far &&"""),
      ("M8 in-game menu",
       '                        m_duo_fill_blur->draw("Revealed background blur radius (px, 0..12)");',
       """                        m_duo_fill_blur->draw("Revealed background blur radius (px, 0..12)");
                        m_duo_m8_distance->draw("Distance-based depth edges and background fill");
                        if (m_duo_m8_distance->value()) {
                            m_duo_m8_near_m->draw("Near behavior until distance (metres)");
                            m_duo_m8_far_m->draw("Far behavior from distance (metres)");
                            m_duo_m8_edge_near->draw("Close edge smoothing (0 crisp, 1 soft)");
                            m_duo_m8_edge_far->draw("Far edge smoothing (0 crisp, 1 soft)");
                            m_duo_m8_fill_near->draw("Close revealed background fill (0 off, 1 full)");
                            m_duo_m8_fill_far->draw("Far revealed background fill (0 off, 1 full)");
                        }"""),
    ])
    edit(vr/"DuoViewM1D3D12.hpp",[
      ("M8 constant buffer fields",
       "    float m7_controls[4]{};\n    uint32_t m7_color_extent[4]{};\n    float m5_sharpen[4]{};",
       """    float m7_controls[4]{};
    uint32_t m7_color_extent[4]{};
    float m8_distance[4]{};
    float m8_effects[4]{};
    float m5_sharpen[4]{};"""),
      ("M8 constant size",
       "sizeof(M1Constants) == 528", "sizeof(M1Constants) == 560"),
      ("M8 new frozen parameters",
       "const std::array<uint32_t,4>& color_extent) {",
       """const std::array<uint32_t,4>& color_extent,
                         bool distance_edges,float near_m8,float far_m8,
                         float edge_near,float edge_far,float fill_near,float fill_far) {"""),
      ("M8 scale physical distances to inverse engine units",
       "        std::copy(color_extent.begin(),color_extent.end(),data.m7_color_extent);",
       """        std::copy(color_extent.begin(),color_extent.end(),data.m7_color_extent);
        const float world_units=(std::max)(geometry.world_to_meters,1.f);
        const float near_distance=(std::max)(near_m8,.25f);
        const float far_distance=(std::max)(far_m8,near_distance+.1f);
        data.m8_distance[0]=1.f/(near_distance*world_units);
        data.m8_distance[1]=1.f/(far_distance*world_units);
        data.m8_distance[2]=distance_edges ? 1.f : 0.f;
        data.m8_effects[0]=edge_near;
        data.m8_effects[1]=edge_far;
        data.m8_effects[2]=fill_near;
        data.m8_effects[3]=fill_far;"""),
    ])
    edit(vr/"DuoViewD3D12.hpp",[
      ("M8 source settings into compositor constants",
       "settings.edge_history,settings.fill_history,settings.fill_blur_px,color_extent);",
       """settings.edge_history,settings.fill_history,settings.fill_blur_px,color_extent,
                settings.m8_distance,settings.m8_near_m,settings.m8_far_m,
                settings.m8_edge_near,settings.m8_edge_far,
                settings.m8_fill_near,settings.m8_fill_far);"""),
    ])

def main():
    if len(sys.argv)!=3:
        raise SystemExit("Usage: apply_duoview_m8_distance.py <backend> <shaders>")
    shaders(Path(sys.argv[2]))
    backend(Path(sys.argv[1])/"src/mods")
    print("M8: independent distance-aware fine edge smoothness and fill; M7 temporal retained")

if __name__=="__main__":
    main()
