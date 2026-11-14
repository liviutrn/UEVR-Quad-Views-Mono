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
        "    float4 M7Controls;\n    uint4 M7ColorExtent;\n    float4 M7Tuning; // x: maximum temporal edge correction in output pixels\n    float4 M5Sharpen;",
        "    float4 M7Controls;\n    uint4 M7ColorExtent;\n"
        "    float4 M8Distance; // xyz: inverse near/far/enabled; w: temporal reach\n"
        "    float4 M8Effects;  // near/far smoothing, near/far fill\n"
        "    float4 M9PerEye; // near/far intensity of asymmetric eye edges\n"
        "    float4 M5Sharpen;", "M8 shader constants")
    anchor = "// Fine NGX depth is sampled only during conditioning"
    helpers = r"""// All depths passed here are inverse *engine* units from M4, not metres.
// The CPU converts the user-specified distance thresholds using world_to_meters.
float M8FarWeight(float inverseDepth) {
    // Avoid an early return in the helper reached from a group-synchronized
    // compute loop; FXC/WARP can lower it into unsafe divergent control flow.
    const float enabled=step(.5,M8Distance.z);
    const float span=max(M8Distance.x-M8Distance.y,1.e-8);
    const float t=saturate((M8Distance.x-inverseDepth)/span);
    return enabled*(t*t*(3.-2.*t));
}
float M8SeedScale(float inverseDepth) {
    const float smoothness=lerp(M8Effects.x,M8Effects.y,M8FarWeight(inverseDepth));
    return lerp(2.0,.35,saturate(smoothness));
}
float M8SafeLimit() {
    const float kmax=max(max(abs(M1Eye.x),abs(M1Eye.y)),.00001);
    const float cropWidth=max(M2Crop.z-M2Crop.x,1.e-5);
    return .99*cropWidth/max(kmax*float(M4Grid.x),.00001);
}
float M8AdjustedPenalty(float inverseDepth, float original) {
    // One return and no branch in the inner envelope iteration. M8 OFF
    // selects original exactly; M8 ON retains the same proposed slope.
    const float enabled=step(.5,M8Distance.z);
    const float smoothness=lerp(M8Effects.x,M8Effects.y,M8FarWeight(inverseDepth));
    // Larger penalty => narrower/sharper envelope, smaller => broader/softer.
    const float proposed=original*lerp(2.0,.35,saturate(smoothness));
    // Never make k*dD/du steeper than the warp's no-fold bound.
    const float kmax=max(max(abs(M1Eye.x),abs(M1Eye.y)),.00001);
    // A fovea grid texel spans cropWidth / M4Grid.x in full-eye UV.
    // The no-fold limit is k * d(depth)/d(full-eye-u) < 1, not
    // k * d(depth)/d(fovea-local-u) < 1.
    const float cropWidth=max(M2Crop.z-M2Crop.x,1.e-5);
    const float maxSafe=.99*cropWidth/max(kmax*float(M4Grid.x),.00001);
    return lerp(original,min(proposed,maxSafe),enabled);
}
float M8FillStrength(float inverseDepth) {
    const float enabled=step(.5,M8Distance.z);
    return lerp(1.,saturate(lerp(M8Effects.z,M8Effects.w,M8FarWeight(inverseDepth))),enabled);
}
// 1.0 = original one-sided M3a conditioning, 0.0 = symmetric M4.
// Fade the *asymmetry*, not just its edge penalty, to prevent distant halos.
float M9PerEyeMix(float inverseDepth) {
    const float enabled=step(.5,M8Distance.z);
    return lerp(1.,saturate(lerp(M9PerEye.x,M9PerEye.y,M8FarWeight(inverseDepth))),enabled);
}

// Fine NGX depth is sampled only during conditioning""";
    text=once(text,anchor,helpers,"M8 helper insertion")
    # Pack temporal reach in M8Distance.w instead of an extra float4.
    # This reduces M4 constant traffic and restores the preceding CB offsets.
    text=once(text,"clamp(M7Tuning.x,2.,20.)","clamp(M8Distance.w,2.,20.)",
              "M9 reuse constant register for temporal edge reach")
    text=once(text,
        "groupshared float M1Next[1024];",
        "groupshared float M1Next[1024];\n"
        "groupshared float M8Origin[1024];\n"
        "groupshared float M8NextOrigin[1024];\n"
        "groupshared float M8Scale[1024];\n"
        "groupshared float M8NextScale[1024];",
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
                const float source=M8Distance.z>.5 ? M8Origin[xf] : M1Row[xf];
                // Interpolate one slope, rather than evaluate two candidates.
                const float slope=lerp(M1Filter.x*scale,pf,M9PerEyeMix(source));
                const float candidate=M1Row[xf]-float(step)*M8AdjustedPenalty(source,slope);
                if (candidate>v) { v=candidate; if (M8Distance.z>.5) origin=M8Origin[xf]; }
            }
            if (xs>=0 && xs<int(w)) {
                const float source=M8Distance.z>.5 ? M8Origin[xs] : M1Row[xs];
                const float mix=M9PerEyeMix(source);
                if (ps>0.0 || mix<.999) {
                    // Fade out the directional reverse contribution itself,
                    // not only its slope: at mix=1 and ps=0 there is no
                    // reverse spread. At mix=0 use a symmetric envelope.
                    const float symmetric=max(0.,M1Row[xs]-float(step)*M8AdjustedPenalty(source,M1Filter.x*scale));
                    const float oneSided=ps>0. ?
                        max(0.,M1Row[xs]-float(step)*M8AdjustedPenalty(source,ps)) : 0.;
                    const float candidate=lerp(symmetric,oneSided,mix);
                    if (candidate>v) { v=candidate; if (M8Distance.z>.5) origin=M8Origin[xs]; }
                }
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
    # M9 hardening: the directional branch must not repeatedly evaluate the
    # depth-dependent penalty helper inside a group-synchronized GPU loop.
    # Reuse the already-seeded M8Scale and carry its winning source in lockstep
    # with M8Origin. M8 OFF takes the original scalar penalty path.
    block=once(block,
        "    const int fold=k>=0.0 ? 1 : -1;",
        "    const float safeSlope=M8SafeLimit();\n    const int fold=k>=0.0 ? 1 : -1;",
        "uniform precomputed safe slope")
    block=once(block,
        "            float v=M1Row[x], origin=0.;\n            if (M8Distance.z>.5) origin=M8Origin[x];",
        "            float v=M1Row[x], origin=0., factor=0.;\n            if (M8Distance.z>.5) { origin=M8Origin[x]; factor=M8Scale[x]; }",
        "start carried scale")
    block=once(block,
        "                const float candidate=M1Row[xf]-float(step)*M8AdjustedPenalty(source,slope);",
        "                const float applied= M8Distance.z>.5 ? min(slope*M8Scale[xf],safeSlope) : slope;\n                const float candidate=M1Row[xf]-float(step)*applied;",
        "precomputed foreground penalty")
    block=once(block,
        "                if (candidate>v) { v=candidate; if (M8Distance.z>.5) origin=M8Origin[xf]; }",
        "                if (candidate>v) { v=candidate; if (M8Distance.z>.5) { origin=M8Origin[xf]; factor=M8Scale[xf]; } }",
        "carry foreground factor")
    block=once(block,
        "                    const float symmetric=max(0.,M1Row[xs]-float(step)*M8AdjustedPenalty(source,M1Filter.x*scale));",
        "                    const float symSlope=M8Distance.z>.5 ? min((M1Filter.x*scale)*M8Scale[xs],safeSlope) : (M1Filter.x*scale);\n                    const float symmetric=max(0.,M1Row[xs]-float(step)*symSlope);",
        "precomputed reverse symmetric slope")
    block=once(block,
        "                    const float oneSided=ps>0. ?\n                        max(0.,M1Row[xs]-float(step)*M8AdjustedPenalty(source,ps)) : 0.;",
        "                    const float dirSlope=M8Distance.z>.5 ? min(ps*M8Scale[xs],safeSlope) : ps;\n                    const float oneSided=ps>0. ?\n                        max(0.,M1Row[xs]-float(step)*dirSlope) : 0.;",
        "precomputed reverse one-sided slope")
    block=once(block,
        "                    if (candidate>v) { v=candidate; if (M8Distance.z>.5) origin=M8Origin[xs]; }",
        "                    if (candidate>v) { v=candidate; if (M8Distance.z>.5) { origin=M8Origin[xs]; factor=M8Scale[xs]; } }",
        "carry reverse factor")
    block=once(block,
        "            if (M8Distance.z>.5) M8NextOrigin[x]=origin;",
        "            if (M8Distance.z>.5) { M8NextOrigin[x]=origin; M8NextScale[x]=factor; }",
        "stage next factor")
    block=once(block,
        "            if (M8Distance.z>.5) M8Origin[x]=M8NextOrigin[x];",
        "            if (M8Distance.z>.5) { M8Origin[x]=M8NextOrigin[x]; M8Scale[x]=M8NextScale[x]; }",
        "publish next factor")
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
    # Guard every groupshared address even if FXC speculatively evaluates
    # branch operands for inactive lanes. M4 uses 128 lanes for widths <128.
    # When distance mode is OFF, retain exact pre-M8 penalty arithmetic.
    block=once(block,
       """float l=0.0, r=0.0;
                if (x>=step)
                    l=M1Row[x-step]-float(step)*M8AdjustedPenalty(M8Distance.z>.5 ? M8Origin[x-step] : M1Row[x-step],pen);
                if (x+step<w)
                    r=M1Row[x+step]-float(step)*M8AdjustedPenalty(M8Distance.z>.5 ? M8Origin[x+step] : M1Row[x+step],pen);""",
       """const uint leftIndex=x>=step ? x-step : x;
                const uint rightIndex=x+step<w ? x+step : x;
                const bool distanceOn=M8Distance.z>.5;
                float l=0.0, r=0.0;
                if (x>=step) {
                    const float source=distanceOn ? M8Origin[leftIndex] : M1Row[leftIndex];
                    const float slope=distanceOn ? M8AdjustedPenalty(source,pen) : pen;
                    l=M1Row[leftIndex]-float(step)*slope;
                }
                if (x+step<w) {
                    const float source=distanceOn ? M8Origin[rightIndex] : M1Row[rightIndex];
                    const float slope=distanceOn ? M8AdjustedPenalty(source,pen) : pen;
                    r=M1Row[rightIndex]-float(step)*slope;
                }""",
       "M4 clamp shared addresses and preserve exact M8-off penalty")
    block=once(block,"if (l>v && l>=r) origin=M8Origin[x-step];",
                    "if (l>v && l>=r) origin=M8Origin[leftIndex];",
                    "clamp winning left origin")
    block=once(block,"else if (r>v && r>l) origin=M8Origin[x+step];",
                    "else if (r>v && r>l) origin=M8Origin[rightIndex];",
                    "clamp winning right origin")

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
    # Precompute per-source slope factors before the synchronized loop. Keep
    # the existing source-origin and its factor in lockstep each iteration.
    block=once(block,
        "        M8Origin[x]=M1Row[x];",
        "        M8Origin[x]=M1Row[x];\n        M8Scale[x]=M8SeedScale(M1Row[x]);",
        "seed source slope factor")
    block=once(block,
        "const float pen=M1Filter.x*scale;",
        "const float pen=M1Filter.x*scale;\n        const float m8Safe=M8SafeLimit();",
        "safe penalty cap outside loop")
    block=once(block,
        "const float source=distanceOn ? M8Origin[leftIndex] : M1Row[leftIndex];\n"
        "                    const float slope=distanceOn ? M8AdjustedPenalty(source,pen) : pen;",
        "const float slope=distanceOn ? min(pen*M8Scale[leftIndex],m8Safe) : pen;",
        "left precomputed penalty")
    block=once(block,
        "const float source=distanceOn ? M8Origin[rightIndex] : M1Row[rightIndex];\n"
        "                    const float slope=distanceOn ? M8AdjustedPenalty(source,pen) : pen;",
        "const float slope=distanceOn ? min(pen*M8Scale[rightIndex],m8Safe) : pen;",
        "right precomputed penalty")
    block=once(block,
        """                    float origin=M8Origin[x];
                    if (l>v && l>=r) origin=M8Origin[leftIndex];
                    else if (r>v && r>l) origin=M8Origin[rightIndex];
                    M8NextOrigin[x]=origin;""",
        """                    float origin=M8Origin[x], factor=M8Scale[x];
                    if (l>v && l>=r) { origin=M8Origin[leftIndex]; factor=M8Scale[leftIndex]; }
                    else if (r>v && r>l) { origin=M8Origin[rightIndex]; factor=M8Scale[rightIndex]; }
                    M8NextOrigin[x]=origin;
                    M8NextScale[x]=factor;""",
        "carry winning depth/factor")
    block=once(block,
        "if (M8Distance.z>.5) M8Origin[x]=M8NextOrigin[x];",
        "if (M8Distance.z>.5) { M8Origin[x]=M8NextOrigin[x]; M8Scale[x]=M8NextScale[x]; }",
        "publish winning factor")
    block=once(block,
        "if (M8Distance.z>.5) M8Origin[x]=M1Seed[x];",
        "if (M8Distance.z>.5) { M8Origin[x]=M1Seed[x]; M8Scale[x]=M8SeedScale(M1Seed[x]); }",
        "reset right-eye factor")
    block=uniformize_lane_loops(block)
    # WARP-only differential probes: clone the *generated* M4 seed, and
    # then clone the entire kernel with a compile-time symmetric branch.
    # These retain the exact seed/history instructions and uniform barriers.
    # The shipping HLSL can contain unused probe functions; no probe PSOs
    # or environment switches are compiled into its C++ backend.
    marker="[numthreads(128,1,1)]"
    main,separator,vertical_attr=block.rpartition(marker)
    if not separator or not main.endswith("}\n\n"):
        raise RuntimeError("M4 probe extraction: missing vertical attribute")
    seed_head=main.split("    GroupMemoryBarrierWithGroupSync();",1)[0]
    if "void CSConditionM4(" not in seed_head:
        raise RuntimeError("M4 probe extraction: seed head missing")
    seed=marker+"\n"+seed_head.replace("void CSConditionM4(","void CSConditionM4ProbeSeed(",1)
    seed += """    GroupMemoryBarrierWithGroupSync();
    for (uint x=lane; x<w; x+=128u) {
        M4FoveaConditioned[uint3(x,group.x,0u)]=M1Row[x];
        M4FoveaConditioned[uint3(x,group.x,1u)]=M1Row[x];
    }
}
"""
    legacy=marker+"\n"+seed_head.replace("void CSConditionM4(","void CSConditionM4ProbeLegacy(",1)
    legacy += """    GroupMemoryBarrierWithGroupSync();
    const float limit=M1Depth.w>0.0 ? 2.0*M1Depth.w : M1Filter.y;
    const float pen=M1Filter.x*M4Flags.y;
    for (uint step=1u;step<w && float(step-1u)*pen<limit;step*=2u) {
        for (uint tile=0u;tile<(w+127u)/128u;++tile) {
            const uint x=128u*tile+lane;
            if(x<w) {
                const uint xl=x>=step ? x-step : x;
                const uint xr=x+step<w ? x+step : x;
                const float l=x>=step ? M1Row[xl]-float(step)*pen : 0.0;
                const float r=x+step<w ? M1Row[xr]-float(step)*pen : 0.0;
                M1Next[x]=max(M1Row[x],max(l,r));
            }
        }
        GroupMemoryBarrierWithGroupSync();
        for (uint tile=0u;tile<(w+127u)/128u;++tile) {
            const uint x=128u*tile+lane;
            if(x<w) M1Row[x]=M1Next[x];
        }
        GroupMemoryBarrierWithGroupSync();
    }
    for (uint tile=0u;tile<(w+127u)/128u;++tile) {
        const uint x=128u*tile+lane;
        if(x<w) {
            M4FoveaConditioned[uint3(x,group.x,0u)]=M1Row[x];
            M4FoveaConditioned[uint3(x,group.x,1u)]=M1Row[x];
        }
    }
}
"""
    symmetric=marker+"\n"+main.replace("void CSConditionM4(","void CSConditionM4ProbeSymmetric(",1)
    symmetric=symmetric.replace("[branch] if (M3Flags.x<.5)", "if (true)",1)
    if symmetric.count("if (true)")!=1:
        raise RuntimeError("M4 symmetric probe branch absent")
    # Isolate M8's origin propagation from its per-source penalty function.
    # Both probes force the symmetric M4 branch at compile time.
    no_origin=symmetric.replace("CSConditionM4ProbeSymmetric(","CSConditionM4ProbeNoOrigin(",1)
    no_origin=once(no_origin,
        "        M8Origin[x]=M1Row[x];",
        "        // source origins intentionally disabled for this probe",
        "no-origin seed")
    no_origin=once(no_origin,
        """                if (M8Distance.z>.5) {
                    float origin=M8Origin[x], factor=M8Scale[x];
                    if (l>v && l>=r) { origin=M8Origin[leftIndex]; factor=M8Scale[leftIndex]; }
                    else if (r>v && r>l) { origin=M8Origin[rightIndex]; factor=M8Scale[rightIndex]; }
                    M8NextOrigin[x]=origin;
                    M8NextScale[x]=factor;
                }""",
        "                // No source-origin propagation in this probe.",
        "no-origin candidate")
    no_origin=no_origin.replace("M8Origin[leftIndex]","M1Row[leftIndex]")
    no_origin=no_origin.replace("M8Origin[rightIndex]","M1Row[rightIndex]")
    no_origin=no_origin.replace("if (M8Distance.z>.5) { M8Origin[x]=M8NextOrigin[x]; M8Scale[x]=M8NextScale[x]; }",
                                "// No origin-history update")
    origin_only=symmetric.replace("CSConditionM4ProbeSymmetric(","CSConditionM4ProbeOriginOnly(",1)
    if origin_only.count("const float slope=distanceOn ? min(pen*M8Scale[")!=2:
        raise RuntimeError("M4 origin-only probe expected two penalty operations")
    origin_only=origin_only.replace("const float slope=distanceOn ? min(pen*M8Scale[leftIndex],m8Safe) : pen;",
                                    "const float slope=pen;")
    origin_only=origin_only.replace("const float slope=distanceOn ? min(pen*M8Scale[rightIndex],m8Safe) : pen;",
                                    "const float slope=pen;")
    block=main+"\n"+seed+"\n"+symmetric+"\n"+legacy+"\n"+no_origin+"\n"+origin_only+"\n"+marker+vertical_attr
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
       "    float edge_history{.70f}, fill_history{.65f}, fill_blur_px{1.25f}, edge_reach_px{8.f};",
       """    float edge_history{.70f}, fill_history{.65f}, fill_blur_px{1.25f}, edge_reach_px{8.f};
    bool m8_distance{false}; // OFF preserves M7 output exactly
    float m8_near_m{2.f}, m8_far_m{5.f};
    float m8_edge_near{0.f}, m8_edge_far{1.f};
    float m8_fill_near{1.f}, m8_fill_far{0.f};
    float m9_eye_near{1.f}, m9_eye_far{0.f}; // 1=directional, 0=symmetric (requires M8)"""),
      ("M8 validation",
       "        out.fill_blur_px=(std::clamp)(requested.fill_blur_px,0.f,32.f);",
       """        out.fill_blur_px=(std::clamp)(requested.fill_blur_px,0.f,32.f);
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
        out.m8_fill_far=(std::clamp)(requested.m8_fill_far,0.f,1.f);
    if(std::isfinite(requested.m9_eye_near))
        out.m9_eye_near=(std::clamp)(requested.m9_eye_near,0.f,1.f);
    if(std::isfinite(requested.m9_eye_far))
        out.m9_eye_far=(std::clamp)(requested.m9_eye_far,0.f,1.f);"""),
    ])
    edit(mods/"VR.hpp",[
      ("M8 persistent controls",
       "    const ModSlider::Ptr m_duo_fill_blur{ModSlider::create(generate_name(\"DuoFillBlurPixels\"),0.f,32.f,1.25f)};",
       """    const ModSlider::Ptr m_duo_fill_blur{ModSlider::create(generate_name("DuoFillBlurPixels"),0.f,32.f,1.25f)};
    const ModToggle::Ptr m_duo_m8_distance{ModToggle::create(generate_name("DuoM8DistanceEdges"),false)};
    const ModSlider::Ptr m_duo_m8_near_m{ModSlider::create(generate_name("DuoM8StartMeters"),.25f,50.f,2.f)};
    const ModSlider::Ptr m_duo_m8_far_m{ModSlider::create(generate_name("DuoM8EndMeters"),.5f,100.f,5.f)};
    const ModSlider::Ptr m_duo_m8_edge_near{ModSlider::create(generate_name("DuoM8EdgeNear"),0.f,1.f,0.f)};
    const ModSlider::Ptr m_duo_m8_edge_far{ModSlider::create(generate_name("DuoM8EdgeFar"),0.f,1.f,1.f)};
    const ModSlider::Ptr m_duo_m8_fill_near{ModSlider::create(generate_name("DuoM8FillNear"),0.f,1.f,1.f)};
    const ModSlider::Ptr m_duo_m8_fill_far{ModSlider::create(generate_name("DuoM8FillFar"),0.f,1.f,0.f)};
    const ModSlider::Ptr m_duo_m9_eye_near{ModSlider::create(generate_name("DuoM9PerEyeNear"),0.f,1.f,1.f)};
    const ModSlider::Ptr m_duo_m9_eye_far{ModSlider::create(generate_name("DuoM9PerEyeFar"),0.f,1.f,0.f)};"""),
      ("M8 settings persist",
       "*m_duo_edge_history, *m_duo_fill_history, *m_duo_fill_blur,",
       """*m_duo_edge_history, *m_duo_fill_history, *m_duo_fill_blur,
            *m_duo_m8_distance, *m_duo_m8_near_m, *m_duo_m8_far_m,
            *m_duo_m8_edge_near, *m_duo_m8_edge_far, *m_duo_m8_fill_near, *m_duo_m8_fill_far,
            *m_duo_m9_eye_near, *m_duo_m9_eye_far,"""),
    ])
    edit(mods/"VR.cpp",[
      ("M8 reset",
       "                    m_duo_fill_blur->value()=1.25f;",
       """                    m_duo_fill_blur->value()=1.25f;
                    m_duo_m8_distance->value()=false;
                    m_duo_m8_near_m->value()=2.f; m_duo_m8_far_m->value()=5.f;
                    m_duo_m8_edge_near->value()=0.f; m_duo_m8_edge_far->value()=1.f;
                    m_duo_m8_fill_near->value()=1.f; m_duo_m8_fill_far->value()=0.f;
                    m_duo_m9_eye_near->value()=1.f; m_duo_m9_eye_far->value()=0.f;"""),
      ("M8 frozen profile",
       "        .fill_blur_px=m_duo_fill_blur->value(),\n        .edge_reach_px=m_duo_edge_reach->value(),",
       """        .fill_blur_px=m_duo_fill_blur->value(),
        .edge_reach_px=m_duo_edge_reach->value(),
        .m8_distance=m_duo_m8_distance->value(),
        .m8_near_m=m_duo_m8_near_m->value(), .m8_far_m=m_duo_m8_far_m->value(),
        .m8_edge_near=m_duo_m8_edge_near->value(), .m8_edge_far=m_duo_m8_edge_far->value(),
        .m8_fill_near=m_duo_m8_fill_near->value(), .m8_fill_far=m_duo_m8_fill_far->value(),
        .m9_eye_near=m_duo_m9_eye_near->value(), .m9_eye_far=m_duo_m9_eye_far->value(),"""),
      ("M8 live changes",
       "        current.fill_blur_px==candidate.fill_blur_px &&\n        current.edge_reach_px==candidate.edge_reach_px &&",
       """        current.fill_blur_px==candidate.fill_blur_px &&
        current.edge_reach_px==candidate.edge_reach_px &&
        current.m8_distance==candidate.m8_distance &&
        current.m8_near_m==candidate.m8_near_m && current.m8_far_m==candidate.m8_far_m &&
        current.m8_edge_near==candidate.m8_edge_near && current.m8_edge_far==candidate.m8_edge_far &&
        current.m8_fill_near==candidate.m8_fill_near && current.m8_fill_far==candidate.m8_fill_far &&
        current.m9_eye_near==candidate.m9_eye_near && current.m9_eye_far==candidate.m9_eye_far &&"""),
      ("M8 in-game menu",
       '                        m_duo_fill_blur->draw("Revealed background blur radius (output px, 0..32)");',
       """                        m_duo_fill_blur->draw("Revealed background blur radius (output px, 0..32)");
                        m_duo_m8_distance->draw("Distance-based depth edges and background fill");
                        if (m_duo_m8_distance->value()) {
                            m_duo_m8_near_m->draw("Near behavior until distance (metres)");
                            m_duo_m8_far_m->draw("Far behavior from distance (metres)");
                            m_duo_m8_edge_near->draw("Close edge smoothing (0 crisp, 1 soft)");
                            m_duo_m8_edge_far->draw("Far edge smoothing (0 crisp, 1 soft)");
                            m_duo_m8_fill_near->draw("Close revealed background fill (0 off, 1 full)");
                            m_duo_m8_fill_far->draw("Far revealed background fill (0 off, 1 full)");
                            if (m_duo_m3_edges->value()) {
                                m_duo_m9_eye_near->draw("Close per-eye edge asymmetry (1 directional, 0 symmetric)");
                                m_duo_m9_eye_far->draw("Far per-eye edge asymmetry (1 directional, 0 symmetric)");
                            }
                        }"""),
    ])
    edit(vr/"DuoViewM1D3D12.hpp",[
      ("M8 constant buffer fields",
       "    float m7_controls[4]{};\n    uint32_t m7_color_extent[4]{};\n    float m7_tuning[4]{};\n    float m5_sharpen[4]{};",
       """    float m7_controls[4]{};
    uint32_t m7_color_extent[4]{};
    float m8_distance[4]{};
    float m8_effects[4]{};
    float m9_per_eye[4]{};
    float m5_sharpen[4]{};"""),
      ("M8 constant size",
       "sizeof(M1Constants) == 544", "sizeof(M1Constants) == 576"),
      ("M8 new frozen parameters",
       "const std::array<uint32_t,4>& color_extent) {",
       """const std::array<uint32_t,4>& color_extent,
                         bool distance_edges,float near_m8,float far_m8,
                         float edge_near,float edge_far,float fill_near,float fill_far,
                         float eye_near,float eye_far) {"""),
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
        data.m8_effects[3]=fill_far;
        data.m9_per_eye[0]=eye_near;
        data.m9_per_eye[1]=eye_far;"""),
    ])
    edit(vr/"DuoViewM1D3D12.hpp",[
      ("reuse M8 distance w for temporal reach",
       "        data.m7_tuning[0]=edge_reach_px;",
       "        data.m8_distance[3]=edge_reach_px;"),
    ])
    edit(vr/"DuoViewD3D12.hpp",[
      ("M8 source settings into compositor constants",
       "settings.edge_history,settings.fill_history,settings.fill_blur_px,\n                settings.edge_reach_px,color_extent);",
       """settings.edge_history,settings.fill_history,settings.fill_blur_px,
                settings.edge_reach_px,color_extent,
                settings.m8_distance,settings.m8_near_m,settings.m8_far_m,
                settings.m8_edge_near,settings.m8_edge_far,
                settings.m8_fill_near,settings.m8_fill_far,
                settings.m9_eye_near,settings.m9_eye_far);"""),
    ])

def main():
    if len(sys.argv)!=3:
        raise SystemExit("Usage: apply_duoview_m8_distance.py <backend> <shaders>")
    shaders(Path(sys.argv[2]))
    backend(Path(sys.argv[1])/"src/mods")
    print("M9: distance-aware per-eye asymmetry, meaningful M7 filters, and M8 controls")

if __name__=="__main__":
    main()
