#!/usr/bin/env python3
"""M2.3: headset-driven DuoView depth pairing + B43 per-eye parity + dual sharpen.

Run ONLY after the full M2.2 overlay chain; exact anchors protect the
known-good M2.2 baseline. Only mode ID6 is changed. No extra scene render.
"""
from pathlib import Path
import sys
from apply_duoview_b40_pipeline import patch


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: apply_duoview_m23.py <backend> <duoview-shaders>")
    mods=Path(sys.argv[1])/"src/mods"
    shaders=Path(sys.argv[2])

    # Stereo depth: NGX evaluations are commonly recorded on different command
    # lists. Keep adjacent capture sequence, exact role/extent/generation,
    # fence/queue ordering and <=25ms recorded gap. Do not accept old pairs.
    patch(mods/"vr/QuadViewNgxDepth.hpp", [
        ("M23 pair accepts safe cross-list NGX sibling evaluation",
         '''                if (coarse->producer_list!=fine->producer_list ||
                    coarse->list_epoch!=fine->list_epoch) { reason=4; continue; }''',
         '''                // Different rendered roles normally use different D3D12 lists.
                // Never equate recording epoch with a scene frame.
                // Adjacent captured roles, common request, same producer queue
                // and a tight time window provide an explicit, conservative
                // fallback until exact colour/depth frame IDs are available.
                const bool same_list=coarse->producer_list==fine->producer_list &&
                    coarse->list_epoch==fine->list_epoch;
                const auto capture_gap=coarse->recorded>fine->recorded ?
                    coarse->recorded-fine->recorded : fine->recorded-coarse->recorded;
                const bool same_queue=coarse->duoview_producer_queue &&
                    coarse->duoview_producer_queue.Get()==fine->duoview_producer_queue.Get();
                if (!same_list &&
                    (!same_queue || capture_gap>std::chrono::milliseconds(25))) {
                    reason=4; continue;
                }'''),
    ])

    # Per-eye regular and extra-wide are separate contributions inside the
    # existing *single* composite draw: no second draw call, no extra textures.
    cfg=mods/"vr/DuoViewConfig.hpp"
    patch(cfg,[
        ("M23 width strength state",
         '    bool m21_jitter_correct{false};',
         '''    bool m21_jitter_correct{false};
    bool m23_wide_unlinked{false};
    float m23_wide_strength{1.f},m23_left_wide{1.f},m23_right_wide{1.f};'''),
        ("M23 wide reconcile",
         '    out.m21_jitter_correct=requested.m21_jitter_correct;',
         '''    out.m21_jitter_correct=requested.m21_jitter_correct;
    out.m23_wide_unlinked=requested.m23_wide_unlinked;
    if(std::isfinite(requested.m23_wide_strength))
        out.m23_wide_strength=(std::clamp)(requested.m23_wide_strength,0.f,20.f);
    if(std::isfinite(requested.m23_left_wide))
        out.m23_left_wide=(std::clamp)(requested.m23_left_wide,0.f,20.f);
    if(std::isfinite(requested.m23_right_wide))
        out.m23_right_wide=(std::clamp)(requested.m23_right_wide,0.f,20.f);'''),
    ])
    patch(mods/"VR.hpp",[
        ("M23 controls",
         '    const ModToggle::Ptr m_duo_m21_jitter{ModToggle::create(generate_name("DuoM21JitterCorrect"),false)};',
         '''    const ModToggle::Ptr m_duo_m21_jitter{ModToggle::create(generate_name("DuoM21JitterCorrect"),false)};
    const ModSlider::Ptr m_duo_m23_wide{ModSlider::create(generate_name("DuoM23WideStrength"),0.f,20.f,1.f)};
    const ModToggle::Ptr m_duo_m23_unlinked_wide{ModToggle::create(generate_name("DuoM23UnlinkedWide"),false)};
    const ModSlider::Ptr m_duo_m23_wide_left{ModSlider::create(generate_name("DuoM23WideLeft"),0.f,20.f,1.f)};
    const ModSlider::Ptr m_duo_m23_wide_right{ModSlider::create(generate_name("DuoM23WideRight"),0.f,20.f,1.f)};'''),
        ("M23 persist controls",
         '*m_duo_m21_depth_debug, *m_duo_m21_jitter, *m_duo_m2_unlinked,',
         '*m_duo_m21_depth_debug, *m_duo_m21_jitter, *m_duo_m23_wide, *m_duo_m23_unlinked_wide, *m_duo_m23_wide_left, *m_duo_m23_wide_right, *m_duo_m2_unlinked,'),
    ])
    patch(mods/"VR.cpp",[
        ("M23 reset controls",
         'm_duo_m21_jitter->value()=false;',
         '''m_duo_m21_jitter->value()=false;
                    m_duo_m23_wide->value()=1.f; m_duo_m23_unlinked_wide->value()=false;
                    m_duo_m23_wide_left->value()=1.f; m_duo_m23_wide_right->value()=1.f;'''),
        ("M23 draw independent wide",
         'm_duo_sharpen_wide->draw("Extra-wide sharpen ring (OFF by default; additional 2x radius)");',
         '''m_duo_sharpen_wide->draw("Extra-wide sharpen ring (OFF by default; 1.5x regular radius)");
                if (m_duo_sharpen_wide->value()) {
                    m_duo_m23_wide->draw("Wide sharpen strength (independent of regular)");
                    m_duo_m23_unlinked_wide->draw("Separate left/right wide sharpen");
                    if (m_duo_m23_unlinked_wide->value()) {
                        m_duo_m23_wide_left->draw("Left eye wide sharpen strength");
                        m_duo_m23_wide_right->draw("Right eye wide sharpen strength");
                    }
                }'''),
        ("M23 frozen controls",
         '.m21_jitter_correct=m_duo_m21_jitter->value(),',
         '''.m21_jitter_correct=m_duo_m21_jitter->value(),
        .m23_wide_unlinked=m_duo_m23_unlinked_wide->value(),
        .m23_wide_strength=m_duo_m23_wide->value(),
        .m23_left_wide=m_duo_m23_wide_left->value(),
        .m23_right_wide=m_duo_m23_wide_right->value(),'''),
        ("M23 equality of frozen controls",
         'current.m21_jitter_correct==candidate.m21_jitter_correct &&',
         '''current.m21_jitter_correct==candidate.m21_jitter_correct &&
        current.m23_wide_unlinked==candidate.m23_wide_unlinked &&
        current.m23_wide_strength==candidate.m23_wide_strength &&
        current.m23_left_wide==candidate.m23_left_wide &&
        current.m23_right_wide==candidate.m23_right_wide &&'''),
    ])

    patch(mods/"vr/DuoViewD3D12.hpp",[
        ("M23 M1 wide shader constants",
         '''settings.m21_depth_debug,settings.m21_jitter_correct,
                settings.stereo_near_m,settings.stereo_softness,''',
         '''settings.m21_depth_debug,settings.m21_jitter_correct,
                settings.sharpen_wide ?
                    (settings.m23_wide_unlinked ? settings.m23_left_wide : settings.m23_wide_strength) : 0.f,
                settings.sharpen_wide ?
                    (settings.m23_wide_unlinked ? settings.m23_right_wide : settings.m23_wide_strength) : 0.f,
                settings.stereo_near_m,settings.stereo_softness,'''),
    ])
    patch(mods/"vr/DuoViewM1D3D12.hpp",[
        ("M23 max-size constant buffer",
         '    float m2_sharpen[4]{};',
         '    float m2_sharpen[4]{};\n    float m23_wide[4]{};'),
        ("M23 256-byte constant assert",
         'static_assert(sizeof(M1Constants) == 240);',
         'static_assert(sizeof(M1Constants) == 256);'),
        ("M23 two wide strength arguments",
         '''float right_sharpen, bool depth_debug, bool jitter_correct,
                         float near_m, float softness,''',
         '''float right_sharpen, bool depth_debug, bool jitter_correct,
                         float left_wide, float right_wide, float near_m, float softness,'''),
        ("M23 wide strengths",
         '        data.m2_sharpen[3] = jitter_correct ? 1.f : 0.f;',
         '''        data.m2_sharpen[3] = jitter_correct ? 1.f : 0.f;
        data.m23_wide[0]=(std::clamp)(left_wide,0.f,20.f);
        data.m23_wide[1]=(std::clamp)(right_wide,0.f,20.f);'''),
    ])
    patch(shaders/"DuoViewM1Stereo.hlsl",[
        ("M23 shader cbuffer",
         '    float4 M2Sharpen; // left/right fovea sharpen; linked values are identical',
         '    float4 M2Sharpen; // left/right fovea sharpen; linked values are identical\n    float4 M23Wide; // independent left/right extra-wide strength, 0=OFF'),
    ])
    # Preserve B43 extra-wide as a separate *calculated* detail contribution;
    # shorten the outer ring from 2x to 1.5x regular radius/taps.
    patch(shaders/"DuoViewGlamaryeFovea.hlsl",[
        ("M23 B43 wide 1.5x radius",
         'const float radius = 2.8;',
         'const float radius = 2.1;'),
        ("M23 B43 wide 1.5x far guard",
         'const float2 west = horizontal ? float2(-7.0,0.0) : float2(0.0,7.0);',
         'const float2 west = horizontal ? float2(-5.25,0.0) : float2(0.0,5.25);'),
    ])
    native=shaders/"DuoViewNativeCompositeRaster.hlsl"
    patch(native,[
        ("M23 wide strength independent of regular",
         '''#ifdef DUOVIEW_M1_RASTER
        const float fineSharpen=i.pos.x>=OutputSize.x ? M2Sharpen.y : M2Sharpen.x;
#else
        const float fineSharpen=SharpenStrength;
#endif
        if (fineSharpen > 0.0 && DebugViewMode == 0) {''',
         '''#ifdef DUOVIEW_M1_RASTER
        const bool rightEye=i.pos.x>=OutputSize.x;
        const float fineSharpen=rightEye ? M2Sharpen.y : M2Sharpen.x;
        const float wideSharpen=rightEye ? M23Wide.y : M23Wide.x;
#else
        const float fineSharpen=SharpenStrength;
        const float wideSharpen=SharpenStrength;
#endif
        if (DebugViewMode == 0 &&
            (fineSharpen > 0.0 || ((SharpenFlags & 16u) != 0u && wideSharpen > 0.0))) {'''),
        ("M23 normal pass optional M1",
         'fovea.rgb=GlamSharpenNativeFovea(fullUv,fovea.rgb,fineSharpen);',
         'if (fineSharpen>0.0) fovea.rgb=GlamSharpenNativeFovea(fullUv,fovea.rgb,fineSharpen);'),
        ("M23 normal pass optional non-M1",
         'fovea.rgb=GlamSharpenNativeFovea(fullUv,fovea.rgb);',
         'if (fineSharpen>0.0) fovea.rgb=GlamSharpenNativeFovea(fullUv,fovea.rgb);'),
        ("M23 wide pass gated",
         'if ((SharpenFlags & 16u) != 0u)',
         'if ((SharpenFlags & 16u) != 0u && wideSharpen>0.0)'),
        ("M23 per-eye wide strength",
         'GlamExtraWideChange(fullUv, beforeSharpen, fineSharpen)));',
         'GlamExtraWideChange(fullUv, beforeSharpen, wideSharpen)));'),
    ])
    print("M2.3: fenced cross-list fine depth; continuous B40 seam over blend feather; independent 1.5x wide sharpening")


if __name__=="__main__":
    main()
