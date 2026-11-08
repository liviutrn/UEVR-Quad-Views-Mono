#!/usr/bin/env python3
"""B39: independent static contract for ambient ROI + temporal RGB averaging."""
from pathlib import Path
import subprocess,sys
root=Path(__file__).resolve().parent
base='d043d5ec009e7290a0e0770615a462fd505e2b4b'
old=subprocess.check_output(['git','-C',str(root.parent),'show',base+':quadview/QuadViewComposite.hlsl'],text=True)
now=(root/'QuadViewComposite.hlsl').read_text(encoding='utf-8')
def body(s,name):
    a=s.index(name);p=s.index('{',a);i=p+1;level=1
    while level:
        level+=(s[i]=='{')-(s[i]=='}');i+=1
    return s[a:i]
for f in (
    'float FocusWeight(', 'float SeamFocusWeight(', 'float4 ScenePixel(',
    'float4 ReadContext(', 'float4 MatchContext(', 'float3 CorrectFocusColor(',
    'float3 GlamSharpenFocus(', 'float3 ReadFocus(', 'float2 WarpContextUv(',
    'bool EdgeDifference(', 'float2 EdgeAnchor('
):
    assert body(old,f)==body(now,f),f+' changed (B38/inward/old warp regression)'
ambient=body(now,'bool AmbientEdgeDifference(')
assert '[unroll] for (int depth=0;depth<3;++depth)' in ambient
assert '[unroll] for (int i=-2;i<=2;++i)' in ambient
assert 'FocusProfile.w*(0.25+0.375*float(depth))' in ambient
assert '0.5*float(i)*FocusProfile.z' in ambient
assert 'delta=sum/max(accepted,1.0)' in ambient
assert 'accepted>=8.0' in ambient and 'fill==0.0' in ambient
match=body(now,'float4 MatchEdgeV2(')
assert 'if (fast > 0.0 && Seam.x<4.5)' in match
assert 'if (Seam.x>4.5)' in match
assert 'correction=slow*stable;' in match
assert 'float3 correction=slow*stable+fast*(target-stable)' in match
update=body(now,'void UpdateEdgeV2(')
assert 'AmbientEdgeDifference(eye,p,side,crop,target)' in update
assert 'EdgeDifference(eye,p,side,crop,target)' in update
assert 'step*=float(elapsed)/(float(max(EdgeHistory.w,1u))+float(elapsed))' in update
assert 'stable+=clamp(step,-EdgeV2.z*seconds,EdgeV2.z*seconds)' in update
assert 'elapsed>250u' in update and 'any(cropDelta>motionTolerance)' in update
assert 'Seam.x>4.5 ? max(1.0,min(FocusProfile.z*0.25,12.0)) : 0.5' in update
h=(root/'QuadViewD3D12.hpp').read_text(encoding='utf-8')
assert 'settings.seam_mode==4 || settings.seam_mode==5' in h
assert 'constants.edge_history[3]=settings.ambient_time_ms;' in h
assert 'constants.focus_profile[2]=settings.ambient_radius_px;' in h
assert 'constants.focus_profile[3]=settings.ambient_inside_px;' in h
assert 'hash_float(settings.ambient_radius_px)' in h and 'hash_word(settings.ambient_time_ms)' in h
assert 'sizeof(ShaderConstants) == 512' in h
settings=(root/'QuadViewSettings.hpp').read_text(encoding='utf-8')
assert 'unsigned_integer(requested.seam_mode,0u,5u' in settings
for field in ('ambient_radius_px','ambient_inside_px','ambient_time_ms'):
    assert 'a.'+field+'==b.'+field in settings
if len(sys.argv)>1:
    b=Path(sys.argv[1])/'src/mods'
    ui=(b/'VR.cpp').read_text(encoding='utf-8')
    opts=(b/'VR.hpp').read_text(encoding='utf-8')
    assert 's_quadview_edge_mode_names, 3)' in opts
    assert 'Edge V3 Ambient Temporal' in opts
    for field in ('ambient_radius_px','ambient_inside_px','ambient_time_ms'):
        assert 'requested.'+field+'=' in ui
    assert 'm_quadview_ambient_time->draw("Ambient temporal average (ms)")' in ui
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
        assert marker in generated and marker in settings, marker
print('B39 static source / UI: 15 area samples, no live pixel mirroring, temporal averaging, B38 inward and B37 warp/queue preserved; WARP still required')
