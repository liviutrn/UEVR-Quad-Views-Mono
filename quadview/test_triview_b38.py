#!/usr/bin/env python3
"""B38: verify old inward feather isolated from all B37 depth/outer code."""
from pathlib import Path
import subprocess,sys
r=Path(__file__).resolve().parent
old=subprocess.check_output(['git','-C',str(r.parent),'show','9a4596a796ec447ada2390922284ac0eb74734d9:quadview/QuadViewComposite.hlsl'],text=True)
now=(r/'QuadViewComposite.hlsl').read_text()
def body(text,name):
    a=text.index(name);start=text.index('{',a);end=start+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[a:end]
for fn in ('float FocusWeight(','float4 ReadContext(','float4 MatchContext(',
           'float4 MatchEdgeV2(','float4 SeamFocusWeight(','float3 CorrectFocusColor(',
           'float3 GlamSharpenFocus(','float3 ReadFocus(','float2 WarpContextUv('):
    assert body(old,fn)==body(now,fn),fn+' changed unexpectedly'
assert old.replace(body(old,'float4 ScenePixel('),body(now,'float4 ScenePixel('),1)==now, 'Other B37 shader paths changed'
for marker in (
    'const float4 rawContext = ReadContext(',
    'float4 context = MatchContext(eye, eyeUv, crop, rawContext);',
    'if (Seam.x > 2.5 && SeamLocal.w > 0.5)',
    'context = lerp(rawContext, context, anchor);',
    'output = lerp(context, focus, weight);',
):
    assert marker in now,marker
h=(r/'QuadViewD3D12.hpp').read_text()
assert 'constants.seam_local[2] = settings.legacy_inward_anchor_px;' in h
assert 'constants.seam_local[3] = settings.legacy_inward_feather ? 1.f : 0.f;' in h
assert 'sizeof(ShaderConstants) == 512' in h
if len(sys.argv)>1:
    b=Path(sys.argv[1])/'src/mods'
    vr=(b/'VR.cpp').read_text()
    vh=(b/'VR.hpp').read_text()
    for marker in (
        'requested.legacy_inward_feather=m_quadview_legacy_inward->value();',
        'requested.legacy_inward_anchor_px=m_quadview_legacy_anchor->value();',
        'm_quadview_legacy_inward->draw("Original inward fovea feather (B27)");',
    ):
        assert marker in vr,marker
    assert 'QuadViewLegacyInwardFeather' in vh
    assert 'QuadViewLegacyInwardAnchorPx' in vh
    assert (b/'vr/QuadViewSettings.hpp').read_text()==(r/'QuadViewSettings.hpp').read_text()
print('B38 isolated old inward feather, unchanged B37 exterior and controls: PASS; production WARP required')
