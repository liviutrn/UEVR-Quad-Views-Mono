#!/usr/bin/env python3
"""M3b P5: runtime fine-depth gate tuning. OFF keeps M2.5a arithmetic."""
import sys
from pathlib import Path
from apply_duoview_b40_pipeline import patch

def main():
    if len(sys.argv)!=3:
        raise SystemExit("Usage: apply_duoview_m3b_gate.py <backend> <shader-dir>")
    mods=Path(sys.argv[1])/"src/mods"
    sh=Path(sys.argv[2])
    patch(sh/"DuoViewM1Stereo.hlsl",[
        ("P5 gate constants",
         "    float4 M3Slopes; // x/y: left/right occlusion-side penalty per grid texel, z/w: disocclusion side (0 = unbounded)\n};",
         "    float4 M3Slopes; // x/y: left/right occlusion-side penalty per grid texel, z/w: disocclusion side (0 = unbounded)\n"
         "    float4 M3bGate; // agree ratio, low ratio, high ratio, contrast\n"
         "    float4 M3bOptions; // x: gate tuning active\n};"),
        ("P5 fine agreement tolerance",
         "M25Agree[lane]=valid && closest<=max(M25Flags.y, .03*fine) ? 1u : 0u;",
         "M25Agree[lane]=valid && closest<=max(M25Flags.y, (M3bOptions.x>.5 ? M3bGate.x : .03)*fine) ? 1u : 0u;"),
        ("P5 contrast threshold",
         "M25Max[0]-M25Min[0]>.1*M25Max[0]) ? 1. : 0.;",
         "M25Max[0]-M25Min[0]>(M3bOptions.x>.5 ? M3bGate.w : .1)*M25Max[0]) ? 1. : 0.;"),
        ("P5 ratio smoothstep",
         "M25TileWrite[group.xy]=float4(smoothstep(.60,.85,ratio),ratio,varied,float(n));",
         "M25TileWrite[group.xy]=float4(smoothstep(M3bOptions.x>.5 ? M3bGate.y : .60,M3bOptions.x>.5 ? M3bGate.z : .85,ratio),ratio,varied,float(n));"),
        ("P5 guard threshold",
         "passing+=v && t.y>=.6 ? 1u : 0u;",
         "passing+=v && t.y>=(M3bOptions.x>.5 ? M3bGate.y : .6) ? 1u : 0u;"),
    ])
    patch(mods/"vr/DuoViewM1D3D12.hpp",[
        ("P5 mirror constants",
         "    float m3_slopes[4]{};\n};\nstatic_assert(sizeof(M1Constants) == 320);",
         "    float m3_slopes[4]{};\n    float m3b_gate[4]{};\n    float m3b_options[4]{};\n};\nstatic_assert(sizeof(M1Constants) == 352);"),
        ("P5 writer parameters",
         "                         bool m3_edges,float m3_fold,bool m3_fill,uint32_t jitter_mode,",
         "                         bool m3_edges,float m3_fold,bool m3_fill,uint32_t jitter_mode,\n"
         "                         bool gate_tuning,float agree_tolerance,float ratio_low,float ratio_high,float contrast,"),
        ("P5 writer default-isolation",
         "        if(jitter_mode==1u || jitter_mode==2u) {",
         "        data.m3b_options[0]=gate_tuning ? 1.f : 0.f;\n"
         "        data.m3b_gate[0]=(std::clamp)(agree_tolerance,0.f,.20f);\n"
         "        data.m3b_gate[1]=(std::clamp)(ratio_low,0.f,1.f);\n"
         "        data.m3b_gate[2]=(std::max)(data.m3b_gate[1]+.001f,(std::clamp)(ratio_high,0.f,1.f));\n"
         "        data.m3b_gate[3]=(std::clamp)(contrast,0.f,1.f);\n"
         "        if(jitter_mode==1u || jitter_mode==2u) {"),
    ])
    patch(mods/"vr/DuoViewD3D12.hpp",[
        ("P5 writer wiring",
         "                settings.m3_edges,settings.m3_fold_sharpness,settings.m3_fill,settings.m3_jitter_mode,\n"
         "                m1_raw_srv_,m2_fovea_srv_);",
         "                settings.m3_edges,settings.m3_fold_sharpness,settings.m3_fill,settings.m3_jitter_mode,\n"
         "                settings.m3b_gate_tuning,settings.m3b_agree_tolerance,settings.m3b_ratio_low,\n"
         "                settings.m3b_ratio_high,settings.m3b_contrast,\n"
         "                m1_raw_srv_,m2_fovea_srv_);"),
    ])
    patch(mods/"vr/DuoViewConfig.hpp",[
        ("P5 settings",
         "    uint32_t m3_jitter_mode{0}; // 0=legacy toggle, 1=+jitter, 2=-jitter",
         "    uint32_t m3_jitter_mode{0}; // 0=legacy toggle, 1=+jitter, 2=-jitter\n"
         "    bool m3b_gate_tuning{false};\n    float m3b_agree_tolerance{.03f};\n"
         "    float m3b_ratio_low{.60f};\n    float m3b_ratio_high{.85f};\n    float m3b_contrast{.10f};"),
        ("P5 validate",
         "    out.m3_jitter_mode=(std::min)(requested.m3_jitter_mode,2u);",
         "    out.m3_jitter_mode=(std::min)(requested.m3_jitter_mode,2u);\n"
         "    out.m3b_gate_tuning=requested.m3b_gate_tuning;\n"
         "    if(std::isfinite(requested.m3b_agree_tolerance)) out.m3b_agree_tolerance=(std::clamp)(requested.m3b_agree_tolerance,0.f,.20f);\n"
         "    if(std::isfinite(requested.m3b_ratio_low)) out.m3b_ratio_low=(std::clamp)(requested.m3b_ratio_low,0.f,.99f);\n"
         "    if(std::isfinite(requested.m3b_ratio_high)) out.m3b_ratio_high=(std::clamp)(requested.m3b_ratio_high,0.f,1.f);\n"
         "    out.m3b_ratio_high=(std::max)(out.m3b_ratio_low+.001f,out.m3b_ratio_high);\n"
         "    if(std::isfinite(requested.m3b_contrast)) out.m3b_contrast=(std::clamp)(requested.m3b_contrast,0.f,1.f);"),
    ])
    patch(mods/"VR.hpp",[
        ("P5 controls",
         '    const ModCombo::Ptr m_duo_m3_jitter{ModCombo::create(generate_name("DuoM3JitterMode"),s_duo_m3_jitter_modes,0)};',
         '    const ModCombo::Ptr m_duo_m3_jitter{ModCombo::create(generate_name("DuoM3JitterMode"),s_duo_m3_jitter_modes,0)};\n'
         '    const ModToggle::Ptr m_duo_m3b_gate{ModToggle::create(generate_name("DuoM3bGateTune"),false)};\n'
         '    const ModSlider::Ptr m_duo_m3b_agree{ModSlider::create(generate_name("DuoM25AgreeTolerance"),0.f,.20f,.03f)};\n'
         '    const ModSlider::Ptr m_duo_m3b_low{ModSlider::create(generate_name("DuoM25RatioLow"),0.f,.99f,.60f)};\n'
         '    const ModSlider::Ptr m_duo_m3b_high{ModSlider::create(generate_name("DuoM25RatioHigh"),0.f,1.f,.85f)};\n'
         '    const ModSlider::Ptr m_duo_m3b_contrast{ModSlider::create(generate_name("DuoM25Contrast"),0.f,1.f,.10f)};'),
        ("P5 persisted",
         '            *m_duo_m25_fine_mode, *m_duo_m3_edges, *m_duo_m3_fold, *m_duo_m3_fill, *m_duo_m3_jitter, *m_duo_m2_fovea_depth,',
         '            *m_duo_m25_fine_mode, *m_duo_m3_edges, *m_duo_m3_fold, *m_duo_m3_fill, *m_duo_m3_jitter,\n'
         '            *m_duo_m3b_gate, *m_duo_m3b_agree, *m_duo_m3b_low, *m_duo_m3b_high, *m_duo_m3b_contrast, *m_duo_m2_fovea_depth,'),
    ])
    patch(mods/"VR.cpp",[
        ("P5 reset",
         "                    m_duo_m3_fill->value()=true; m_duo_m3_jitter->value()=0;",
         "                    m_duo_m3_fill->value()=true; m_duo_m3_jitter->value()=0;\n"
         "                    m_duo_m3b_gate->value()=false; m_duo_m3b_agree->value()=.03f;\n"
         "                    m_duo_m3b_low->value()=.60f; m_duo_m3b_high->value()=.85f; m_duo_m3b_contrast->value()=.10f;"),
        ("P5 freeze",
         "        .m3_jitter_mode=uint32_t((std::clamp)(m_duo_m3_jitter->value(),0,2)),",
         "        .m3_jitter_mode=uint32_t((std::clamp)(m_duo_m3_jitter->value(),0,2)),\n"
         "        .m3b_gate_tuning=m_duo_m3b_gate->value(),\n"
         "        .m3b_agree_tolerance=m_duo_m3b_agree->value(),\n"
         "        .m3b_ratio_low=m_duo_m3b_low->value(),\n"
         "        .m3b_ratio_high=m_duo_m3b_high->value(),\n"
         "        .m3b_contrast=m_duo_m3b_contrast->value(),"),
        ("P5 equality",
         "        current.m3_jitter_mode==candidate.m3_jitter_mode &&",
         "        current.m3_jitter_mode==candidate.m3_jitter_mode &&\n"
         "        current.m3b_gate_tuning==candidate.m3b_gate_tuning &&\n"
         "        current.m3b_agree_tolerance==candidate.m3b_agree_tolerance &&\n"
         "        current.m3b_ratio_low==candidate.m3b_ratio_low &&\n"
         "        current.m3b_ratio_high==candidate.m3b_ratio_high &&\n"
         "        current.m3b_contrast==candidate.m3b_contrast &&"),
        ("P5 menu",
         '                    m_duo_m21_depth_debug->draw("Depth debug (0=off, 1=conditioned, 2=fine weight, 3=disagreement)");',
         '                    m_duo_m21_depth_debug->draw("Depth debug (0=off, 1=conditioned, 2=fine weight, 3=disagreement)");\n'
         '                    ImGui::TextWrapped("Quality A/B (M3b):");\n'
         '                    m_duo_m3b_gate->draw("Tune fine-depth gate (OFF = M2.5a constants)");\n'
         '                    if (m_duo_m3b_gate->value()) {\n'
         '                        m_duo_m3b_agree->draw("Fine/coarse agreement tolerance (fraction of fine depth)");\n'
         '                        m_duo_m3b_low->draw("Gate ratio low (zero weight below)");\n'
         '                        m_duo_m3b_high->draw("Gate ratio high (full weight above)");\n'
         '                        m_duo_m3b_contrast->draw("Tile depth contrast threshold");\n'
         '                    }'),
    ])
    print("M3b P5 fine-depth gate tuning installed")

if __name__=="__main__":
    main()
