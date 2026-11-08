#!/usr/bin/env python3
"""B38: verify old inward feather isolated from all B37 depth/outer code."""
from pathlib import Path
import subprocess,sys
r=Path(__file__).resolve().parent
old=subprocess.check_output(['git','-C',str(r.parent),'show','d043d5ec009e7290a0e0770615a462fd505e2b4b:quadview/QuadViewComposite.hlsl'],text=True)
now=(r/'QuadViewComposite.hlsl').read_text()
def body(text,name):
    a=text.index(name);start=text.index('{',a);end=start+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[a:end]
for fn in ('float FocusWeight(','float4 ReadContext(','float4 MatchContext(',
           'float SeamFocusWeight(','float3 CorrectFocusColor(',
           'float3 GlamSharpenFocus(','float3 ReadFocus(','float2 WarpContextUv('):
    assert body(old,fn)==body(now,fn),fn+' changed unexpectedly'
assert body(old,'float4 ScenePixel(')==body(now,'float4 ScenePixel('), 'B38 inward feather changed'
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
    generated=(b/'vr/QuadViewSettings.hpp').read_text()
    # The generated header intentionally adds B8 per-eye sharpen fields.
    # Verify the NEW settings' source-to-backend parity, not whole-file identity.
    for marker in (
        'bool legacy_inward_feather{true}',
        'float legacy_inward_anchor_px{12.f}',
        'float ambient_radius_px{48.f}',
        'float ambient_inside_px{32.f}',
        'uint32_t ambient_time_ms{350u}',
        'out.legacy_inward_feather=requested.legacy_inward_feather;',
        'scalar(requested.legacy_inward_anchor_px,2.f,64.f',
        'scalar(requested.ambient_radius_px,8.f,128.f',
        'scalar(requested.ambient_inside_px,8.f,96.f',
        'unsigned_integer(requested.ambient_time_ms,50u,1500u',
        'unsigned_integer(requested.seam_mode,0u,5u',
        'a.ambient_radius_px==b.ambient_radius_px',
        'a.ambient_inside_px==b.ambient_inside_px',
        'a.ambient_time_ms==b.ambient_time_ms',
    ):
        assert marker in generated and marker in (r/'QuadViewSettings.hpp').read_text(), marker
print('B38 isolated old inward feather, unchanged B37 exterior and controls: PASS; production WARP required')
