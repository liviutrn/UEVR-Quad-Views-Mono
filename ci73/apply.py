"""CI73: conservative stability A/B patch over exact CI72 rendered source."""
from pathlib import Path
import base64,zlib,hashlib,subprocess,sys
PAYLOAD="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"
EXPECTED_SHA="c20fae509873fe07fdbfefe92a17aacc9ef4cdb9f6d18400f140da1c65eb1e32"
FILES=['mods/VR.cpp','mods/VR.hpp','mods/vr/D3D12Component.cpp','mods/vr/DuoViewD3D12.hpp','mods/vr/DuoViewStereoCompositeRaster.hlsl','mods/vr/DuoViewSurfaceReproject.hlsl']
if __name__=="__main__":
 if len(sys.argv)!=2:raise SystemExit("usage: ci73/apply.py BACKEND")
 root=Path(sys.argv[1]).resolve()
 patch=zlib.decompress(base64.b64decode(PAYLOAD))
 if hashlib.sha256(patch).hexdigest()!=EXPECTED_SHA:raise RuntimeError("CI73 patch data hash mismatch")
 for path in FILES:
  p=root/"src"/path
  if not p.exists():raise RuntimeError("CI73 missing source "+path)
  p.write_bytes(p.read_bytes().replace(b"\r\n",b"\n"))
 for cmd in (["git","apply","--check","--unsafe-paths","-"],["git","apply","--unsafe-paths","-"]):
  done=subprocess.run(cmd,cwd=root,input=patch,capture_output=True)
  if done.returncode:raise RuntimeError("CI73 patch failed "+done.stderr.decode(errors="replace"))
 # CI73 exact fixture calibration: protect hands within 80 Unreal cm,
 # not the 100-cm synthetic plane. Keep true native eye color in the
 # cropped fovea where target-depth foreground is unambiguously present.
 # Note: root patch hash is unchanged; the following upgrades are exact.
 p=root/"src/mods/vr/DuoViewStereoCompositeRaster.hlsl"
 text=p.read_text()
 a='if(z>0.f && z<180.f)return true;'
 b='if(z>0.f && z<80.f)return true;'
 if text.count(a)!=1:raise RuntimeError("CI73 hand depth calibration anchor drift")
 text=text.replace(a,b)
 a='if(chooseFovea)return float4(leftFovea.rgb,1.f);'
 b='if(chooseFovea)return right?float4(realRight.rgb,1.f):float4(leftFovea.rgb,1.f);'
 if text.count(a)!=1:raise RuntimeError("CI73 native-eye foreground anchor drift")
 p.write_text(text.replace(a,b))
 p=root/"src/mods/vr/DuoViewSurfaceReproject.hlsl"
 text=p.read_text()
 a='if(MeshConfig.z==0u && MeshQuality.w>=7.5f && targetZ<180.f)discard;'
 b='if(MeshConfig.z==0u && MeshQuality.w>=7.5f && targetZ<80.f)discard;'
 if text.count(a)!=1:raise RuntimeError("CI73 forward model near veto anchor drift")
 p.write_text(text.replace(a,b))
 # Close the RIGHT-fovea transition gap: high-res LEFT reconstruction must
 # have a 5-texel neighborhood with stable confidence, not merely one valid
 # center pixel, before replacing native RIGHT color.
 p=root/"src/mods/vr/DuoViewStereoCompositeRaster.hlsl"
 text=p.read_text()
 old='''        const float4 projected=SyntheticRightFovea.SampleLevel(
            LinearClamp,saturate(local),0);
        return projected.a>=.99f ? float4(projected.rgb/max(projected.a,1.e-5f),1.f)
                                 : float4(realRight.rgb,1.f);'''
 new='''        // Full 5-tap support near silhouette, or native RIGHT fallback.
        const float2 stepUV=1.f/float2(FoveaRect.zw);
        const float4 projected=SyntheticRightFovea.SampleLevel(
            LinearClamp,saturate(local),0);
        float coverage=projected.a;
        coverage=min(coverage,SyntheticRightFovea.SampleLevel(
            LinearClamp,saturate(local+float2(stepUV.x,0)),0).a);
        coverage=min(coverage,SyntheticRightFovea.SampleLevel(
            LinearClamp,saturate(local-float2(stepUV.x,0)),0).a);
        coverage=min(coverage,SyntheticRightFovea.SampleLevel(
            LinearClamp,saturate(local+float2(0,stepUV.y)),0).a);
        coverage=min(coverage,SyntheticRightFovea.SampleLevel(
            LinearClamp,saturate(local-float2(0,stepUV.y)),0).a);
        return coverage>=.995f ? float4(projected.rgb/max(projected.a,1.e-5f),1.f)
                                : float4(realRight.rgb,1.f);'''
 if text.count(old)!=1:raise RuntimeError("CI73 right-fovea 5-tap edge stability anchor drift")
 p.write_text(text.replace(old,new))
 print("CI73 applied: optional conservative pixel-owner, mono near-field, no displaced-eye RGB blend; preserved CI71/CI72")
