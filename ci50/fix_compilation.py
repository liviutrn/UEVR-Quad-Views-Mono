#!/usr/bin/env python3
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
def replace(rel,before,after):
    p=root/rel;s=p.read_text(encoding="utf-8-sig")
    if s.count(before)!=1:
        raise RuntimeError("%s: expected 1 exact anchor, found %d: %r"%(rel,s.count(before),before))
    p.write_text(s.replace(before,after,1),encoding="utf-8",newline="")
replace("src/mods/vr/d3d12/StockDibrDepth.hpp",
    "std::vector<uevr::duoview::diag::Candidate> snapshot_candidates() {",
    "std::vector<uevr::duoview::diag::Candidate> snapshot_candidates(uint64_t selected_left_serial=0,uint64_t selected_right_serial=0) {")
replace("src/mods/vr/D3D12Component.cpp",
    "auto candidates=m_stock_dibr_depth->snapshot_candidates();",
    "auto candidates=m_stock_dibr_depth->snapshot_candidates(depths.left_serial,depths.right_serial);")
print("CI50: selected fovea/periphery capture serials are bound through the producer and exporter")

# R32G32_FLOAT carries exactly two components, not three. Avoid reading a
# non-existent blue channel when constructing RGB diagnostic previews.
replace("src/mods/vr/d3d12/DuoViewDiagnosticDump.hpp",
    "q[0]=encode(im.bytes_per_pixel>=8 ? component(p,im.format,2) : x);",
    "q[0]=encode((im.format==DXGI_FORMAT_R16G16B16A16_FLOAT || im.format==DXGI_FORMAT_R32G32B32A32_FLOAT) ? component(p,im.format,2) : x);")
print("CI50: corrected two-channel float preview bounds")

# CI50 is a stereo-first experimental build: ID6 starts in mode 5,
# while absent NGX pairs still produce the protected mono fallback.
replace("src/mods/vr/D3D12Component.hpp",
    "std::atomic<uint32_t> m_duo_stereo_mode{0};",
    "std::atomic<uint32_t> m_duo_stereo_mode{5};")
print("CI50: default synthesized stereo ON for DuoView ID6")

# Packed HDR/10-bit source colors are common in UE5. Decode those for
# human-readable screenshots; raw files retain the exact original pixels.
replace("src/mods/vr/d3d12/DuoViewDiagnosticDump.hpp",
    "case DXGI_FORMAT_R11G11B10_FLOAT: case DXGI_FORMAT_R16G16_FLOAT:",
    "case DXGI_FORMAT_R11G11B10_FLOAT: case DXGI_FORMAT_R10G10B10A2_UNORM: case DXGI_FORMAT_B8G8R8X8_UNORM: case DXGI_FORMAT_R16G16_FLOAT:")
replace("src/mods/vr/d3d12/DuoViewDiagnosticDump.hpp",
    "    static float component(const uint8_t* p,DXGI_FORMAT f,int lane) {\n",
    """    static float component(const uint8_t* p,DXGI_FORMAT f,int lane) {
        if(f==DXGI_FORMAT_R11G11B10_FLOAT) {
            uint32_t word{};std::memcpy(&word,p,4);
            const unsigned bits=lane==2?5u:6u;
            const unsigned raw=lane==0 ? (word & 2047u) :
                (lane==1 ? ((word>>11)&2047u) : ((word>>22)&1023u));
            const unsigned exponent=raw>>bits, mantissa=raw&((1u<<bits)-1u);
            if(exponent==31u)return mantissa?std::numeric_limits<float>::quiet_NaN():std::numeric_limits<float>::infinity();
            if(exponent==0u)return std::ldexp(float(mantissa),1-15-int(bits));
            return std::ldexp(float((1u<<bits)+mantissa),int(exponent)-15-int(bits));
        }
""")
replace("src/mods/vr/d3d12/DuoViewDiagnosticDump.hpp",
    "const bool bgra8=im.format==DXGI_FORMAT_B8G8R8A8_UNORM ||",
    "const bool packed10=im.format==DXGI_FORMAT_R10G10B10A2_UNORM;\n                const bool bgra8=im.format==DXGI_FORMAT_B8G8R8A8_UNORM ||\n                    im.format==DXGI_FORMAT_B8G8R8X8_UNORM ||")
replace("src/mods/vr/d3d12/DuoViewDiagnosticDump.hpp",
    "const bool floating=im.format==DXGI_FORMAT_R16G16_SNORM ||",
    "const bool floating=im.format==DXGI_FORMAT_R11G11B10_FLOAT || im.format==DXGI_FORMAT_R16G16_SNORM ||")
replace("src/mods/vr/d3d12/DuoViewDiagnosticDump.hpp",
    "if(rgba8 || bgra8 || floating) {",
    "if(rgba8 || bgra8 || floating || packed10) {")
replace("src/mods/vr/d3d12/DuoViewDiagnosticDump.hpp",
    "else if(bgra8){q[0]=p[0];q[1]=p[1];q[2]=p[2];q[3]=255;}",
    """else if(bgra8){q[0]=p[0];q[1]=p[1];q[2]=p[2];q[3]=255;}
                        else if(packed10){
                            uint32_t word{};std::memcpy(&word,p,4);
                            q[2]=uint8_t((word&1023u)*255u/1023u);
                            q[1]=uint8_t(((word>>10)&1023u)*255u/1023u);
                            q[0]=uint8_t(((word>>20)&1023u)*255u/1023u);
                            q[3]=255;
                        }""")
replace("src/mods/vr/d3d12/DuoViewDiagnosticDump.hpp",
    "q[0]=encode((im.format==DXGI_FORMAT_R16G16B16A16_FLOAT || im.format==DXGI_FORMAT_R32G32B32A32_FLOAT) ? component(p,im.format,2) : x);",
    "q[0]=encode((im.format==DXGI_FORMAT_R11G11B10_FLOAT || im.format==DXGI_FORMAT_R16G16B16A16_FLOAT || im.format==DXGI_FORMAT_R32G32B32A32_FLOAT) ? component(p,im.format,2) : x);")
print("CI50: packed HDR and 10-bit color capture previews supported")
