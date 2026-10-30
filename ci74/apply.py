"""CI74: align CI73 owner masks with RIGHT-depth jitter and gather footprint.

Apply AFTER ci73/apply.py and BEFORE shader embedding. Keeps the 240-byte
b0 ABI and the 63-DWORD surface root signature; reuses reserved padding.
Does not change NGX values or DLSS rendering, physical baseline, or crop.
"""
from pathlib import Path
import sys

def replace(path, old, new, count=1):
    text = path.read_text(encoding="utf-8")
    if text.count(old) != count:
        raise RuntimeError(f"CI74 source anchor drift: {path.name}: {old[:80]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")

def apply(root):
    vr = Path(root) / "src/mods/vr"
    replace(vr / "DuoViewComposite.hlsl",
            "    uint2 StereoPadding;   // complete 16-byte HLSL constant register",
            "    float2 RightDepthJitterUV; // NGX input-pixel jitter / RIGHT active dimensions")
    replace(vr / "DuoViewD3D12.hpp", "    uint32_t stereo_padding[2]{};",
            "    float right_depth_jitter_uv[2]{};")
    replace(vr / "DuoViewD3D12.hpp",
            "        const bool surface_mode=stereoReady && stereoMode>=4u;",
            """        // The final ownership tests must address the SAME jittered RIGHT
        // depth grid as make_surface_constants() and PSBackwardSurface.
        // Do not scale by output size, LEFT size, or foveal crop extent.
        if(stereoReady && ngxGuides[1]) {
            const auto j=ngxGuides[1].jitter_uv();
            constants.right_depth_jitter_uv[0]=j[0];
            constants.right_depth_jitter_uv[1]=j[1];
        }
        const bool surface_mode=stereoReady && stereoMode>=4u;""")
    shader = vr / "DuoViewStereoCompositeRaster.hlsl"
    # DeviceRightDepth also feeds the legacy path; zero-jitter DSV behavior
    # is unchanged. Native DLSS output color remains sampled without jitter.
    replace(shader, "ActiveDepthTexel(uv,RightDepthRect)",
            "ActiveDepthTexel(uv+RightDepthJitterUV,RightDepthRect)", count=3)
    replace(shader,
            """    const int2 p=ActiveDepthTexel(uv+RightDepthJitterUV,RightDepthRect);
    const float z0=RightEyeForwardZ""",
            """    // Same pixel-center 2x2 footprint as target inverse gather, not
    // the nearest sample followed by an asymmetric +X/+Y neighborhood.
    const int2 p=int2(floor(RightDepthRect.xy+
        (uv+RightDepthJitterUV)*RightDepthRect.zw-0.5f));
    const float z0=RightEyeForwardZ""")
    replace(shader, "RightSourceDepth.Load(int3(p,0)));\n    const float z1=",
            "RightSourceDepth.Load(int3(clamp(p,lo,hi),0)));\n    const float z1=")
    print("CI74 applied: RIGHT owner-mask jitter + centered gather footprint; b0 stays 240 bytes")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: ci74/apply.py BACKEND")
    apply(Path(sys.argv[1]).resolve())
