#!/usr/bin/env python3
"""M2.1 jitter diagnostic: A/B switch for grid-space NGX jitter compensation.

M1 OFF-path stays byte-identical. Corrected path samples each producer's
jittered raw depth at unjittered grid centres, then leaves conditioned depth
on the *unjittered* grid. This switch is experimental, initially OFF.
"""
from pathlib import Path
import sys
from apply_duoview_b40_pipeline import patch


def main():
    if len(sys.argv)!=3: raise SystemExit("Usage: apply_duoview_m21_jitter.py <backend> <shader-dir>")
    mods=Path(sys.argv[1])/"src/mods"
    shaders=Path(sys.argv[2])
    patch(mods/"vr/DuoViewConfig.hpp",[
        ("jitter flag after diagnostic",
          "    bool m21_depth_debug{false};",
          "    bool m21_depth_debug{false};\n    bool m21_jitter_correct{false};"),
        ("jitter settings reconcile",
          "    out.m21_depth_debug=requested.m21_depth_debug;",
          "    out.m21_depth_debug=requested.m21_depth_debug;\n"
          "    out.m21_jitter_correct=requested.m21_jitter_correct;"),
    ])
    patch(mods/"VR.hpp",[
        ("jitter option",
         '    const ModToggle::Ptr m_duo_m2_unlinked{',
         '    const ModToggle::Ptr m_duo_m21_jitter{ModToggle::create(generate_name("DuoM21JitterCorrect"),false)};\n'
         '    const ModToggle::Ptr m_duo_m2_unlinked{'),
        ("jitter persisted",
         '            *m_duo_m2_fovea_depth, *m_duo_m21_depth_debug, *m_duo_m2_unlinked,',
         '            *m_duo_m2_fovea_depth, *m_duo_m21_depth_debug, *m_duo_m21_jitter, *m_duo_m2_unlinked,'),
    ])
    patch(mods/"VR.cpp",[
        ("jitter reset",
         'm_duo_m21_depth_debug->value()=false;',
         'm_duo_m21_depth_debug->value()=false;\n                    m_duo_m21_jitter->value()=false;'),
        ("jitter A/B control",
         'm_duo_m21_depth_debug->draw("M2.1 depth edge overlay (unwarped image)");',
         'm_duo_m21_depth_debug->draw("M2.1 depth edge overlay (unwarped image)");\n'
         '                    m_duo_m21_jitter->draw("M2.1 align NGX depth jitter (A/B test; OFF is M1 baseline)");'),
        ("jitter frame setting",
         '.m21_depth_debug=m_duo_m21_depth_debug->value(),',
         '.m21_depth_debug=m_duo_m21_depth_debug->value(),\n'
         '        .m21_jitter_correct=m_duo_m21_jitter->value(),'),
        ("jitter change detection",
         'current.m21_depth_debug==candidate.m21_depth_debug &&',
         'current.m21_depth_debug==candidate.m21_depth_debug &&\n'
         '        current.m21_jitter_correct==candidate.m21_jitter_correct &&'),
    ])
    patch(mods/"vr/DuoViewD3D12.hpp",[
        ("pass jitter flag to constant buffer",
         'settings.m21_depth_debug,settings.stereo_near_m,settings.stereo_softness,',
         'settings.m21_depth_debug,settings.m21_jitter_correct,\n'
         '                settings.stereo_near_m,settings.stereo_softness,'),
    ])
    patch(mods/"vr/DuoViewM1D3D12.hpp",[
        ("jitter writer arg",
         'float right_sharpen, bool depth_debug, float near_m, float softness,',
         'float right_sharpen, bool depth_debug, bool jitter_correct,\n'
         '                         float near_m, float softness,'),
        ("jitter shader flag",
         '        data.m2_sharpen[2] = depth_debug ? 1.f : 0.f;',
         '        data.m2_sharpen[2] = depth_debug ? 1.f : 0.f;\n'
         '        data.m2_sharpen[3] = jitter_correct ? 1.f : 0.f;'),
    ])
    patch(shaders/"DuoViewM1Stereo.hlsl",[
        ("jitter-aware conditioning inputs",
         '        const int2 center = int2((float2(x, group.x) + 0.5) * float2(M1Rect.zw) / float2(M1Grid.xy));',
         '        const float2 unjittered=(float2(x,group.x)+.5)/float2(M1Grid.xy);\n'
         '        const float2 correction=M2Sharpen.w>.5 ? M1Eye.zw : float2(0.0,0.0);\n'
         '        const int2 center=int2((unjittered+correction)*float2(M1Rect.zw));'),
        ("corrected display grid stays unjittered",
         '    const float2 cell=clamp((uv+M1Eye.zw)*float2(M1Grid.xy),',
         '    const float2 aligned=uv+(M2Sharpen.w>.5 ? float2(0.0,0.0) : M1Eye.zw);\n'
         '    const float2 cell=clamp(aligned*float2(M1Grid.xy),'),
    ])
    patch(mods/"vr/D3D12Component.cpp",[
        ("jitter diagnostic log",
         'poolMiB={:.1f}",',
         'poolMiB={:.1f} jitter_fix={}",'),
        ("jitter log arg",
         'double(m21.pool_bytes)/1048576.0);',
         'double(m21.pool_bytes)/1048576.0,\n'
         '                                                packet_frame->config.settings.m21_jitter_correct);'),
    ])
    print("M2.1: optional correctly aligned coarse/fine NGX jitter seed + unjittered depth grid")


if __name__=="__main__":
    main()
