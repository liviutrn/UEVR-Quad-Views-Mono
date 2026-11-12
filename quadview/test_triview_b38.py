#!/usr/bin/env python3
"""B38: verify old inward feather isolated from all B37 depth/outer code."""
from pathlib import Path
import ast,subprocess,sys
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
           'float3 ReadFocus(',  # B43: GlamSharpenFocus checked in test_triview_b23_four_samples.py
          'float2 WarpContextUv('):
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
    # Verify inherited B8 patches against the actual B5-generated header.
    # Canonical QuadViewSettings.hpp deliberately excludes B5-only fields.
    # Reconstructing the entire generated file from it was incorrect.
    canonical=(r/'QuadViewSettings.hpp').read_text()
    generated=(b/'vr/QuadViewSettings.hpp').read_text()
    for marker in (
        'legacy_inward_feather', 'legacy_inward_anchor_px',
        'ambient_radius_px', 'ambient_inside_px', 'ambient_time_ms',
        'unsigned_integer(requested.seam_mode,0u,6u',
    ):
        assert marker in canonical and marker in generated, marker
    overlay=ast.parse((r/'apply_triview_eye_sharpen.py').read_text())
    found=False
    for node in ast.walk(overlay):
        if not (isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and
                node.func.id=='edit' and len(node.args)>=2):
            continue
        try: target=ast.literal_eval(node.args[0])
        except (ValueError,TypeError): continue
        if target!='src/mods/vr/QuadViewSettings.hpp': continue
        found=True
        for before,after in ast.literal_eval(node.args[1]):
            assert after in generated, 'B8 generated settings missing: '+after[:70]
    assert found, 'Missing inherited B8 settings generator'

print('B38 isolated old inward feather, unchanged B37 exterior and controls: PASS; production WARP required')
