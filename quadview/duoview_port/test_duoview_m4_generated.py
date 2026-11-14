#!/usr/bin/env python3
"""Static contracts for the generated M4 (full-resolution fovea depth) sources."""
import re
import sys
from pathlib import Path

failures = []


def need(text, snippet, why, count=1):
    n = text.count(snippet)
    if n != count:
        failures.append(f"{why}: expected {count}x, found {n}x: {snippet[:90]!r}")


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: test_duoview_m4_generated.py <backend> <shaders>")
    mods = Path(sys.argv[1])/"src/mods"
    sh = Path(sys.argv[2])
    hlsl = (sh/"DuoViewM1Stereo.hlsl").read_text(encoding="utf-8")
    raster = (sh/"DuoViewNativeCompositeRaster.hlsl").read_text(encoding="utf-8")
    m1 = (mods/"vr/DuoViewM1D3D12.hpp").read_text(encoding="utf-8")
    dx = (mods/"vr/DuoViewD3D12.hpp").read_text(encoding="utf-8")
    cfg = (mods/"vr/DuoViewConfig.hpp").read_text(encoding="utf-8")
    vrcpp = (mods/"VR.cpp").read_text(encoding="utf-8")
    vrhpp = (mods/"VR.hpp").read_text(encoding="utf-8")

    # cbuffer layout: HLSL order == C++ order, 352 bytes.
    need(hlsl, "    float4 M3Slopes;", "M3 slopes still last before M4")
    i3, ig, ifl = hlsl.find("float4 M3Slopes;"), hlsl.find("uint4 M4Grid;"), hlsl.find("float4 M4Flags;")
    if not (0 < i3 < ig < ifl < hlsl.find("};", i3)):
        failures.append("HLSL cbuffer: M4Grid/M4Flags must follow M3Slopes inside the cbuffer")
    c3, cg, cf = m1.find("float m3_slopes[4]{};"), m1.find("uint32_t m4_grid[4]{};"), m1.find("float m4_flags[4]{};")
    if not (0 < c3 < cg < cf):
        failures.append("C++ M1Constants: m4_grid/m4_flags must follow m3_slopes")
    need(m1, "static_assert(sizeof(M1Constants) == 352);", "constants grew by exactly two 16-byte rows")

    # Registers and kernels.
    need(hlsl, "RWTexture2DArray<float> M4FoveaConditioned : register(u5);", "fovea field UAV u5")
    need(hlsl, "Texture2DArray<float> M4FoveaSoft : register(t8);", "fovea field SRV t8")
    need(hlsl, "void CSConditionM4(", "row kernel")
    need(hlsl, "void CSConditionM4Vertical(", "vertical kernel")
    need(hlsl, "float M1ReadCoarseEye(float2 uv, uint eye) {", "shared-grid read kept intact")
    need(hlsl, "float M1ReadConditionedEye(float2 uv, uint eye) {", "single fovea-aware read used by warp/fill/debug")
    need(hlsl, "[branch] if(M4Flags.x>.5 && M4Grid.x>0u && M4Grid.y>0u) {", "OFF returns the shared grid exactly")
    need(hlsl, "const float pen=M1Filter.x*scale;", "symmetric envelope rescaled to fovea texels")
    need(hlsl, "const float pf=(eye==0u ? M3Slopes.x : M3Slopes.y)*scale;", "per-eye occlusion slope rescaled")
    need(hlsl, "const float ps=(eye==0u ? M3Slopes.z : M3Slopes.w)*scale;", "per-eye disocclusion slope rescaled")
    need(hlsl, "const float pv=M1Filter.z*M4Flags.z;", "vertical penalty rescaled")
    # Coarse seed mapping must match CSConditionM1 exactly.
    need(hlsl, "int2((fullUv+M1CoarseCorrection())*float2(M1Rect.zw))", "M4 coarse seed uses the shared mapping")
    need(hlsl, "int2((unjittered+correction)*float2(M1Rect.zw))", "M1 coarse seed mapping unchanged")
    need(raster, "if(M2Sharpen.z>3.5 && M1Grid.x>0u) {", "depth picture debug 4")

    # Host wiring.
    need(m1, "D3D12_CPU_DESCRIPTOR_HANDLE focus_srv, bool m4_fovea_grid=false) {", "defaulted writer parameter")
    need(m1, "data.m2_sharpen[2] = float((std::min)(depth_debug,4u));", "debug range 0..4")
    need(m1, "m4_condition && m4_vertical && m4_depth) {", "M4 only when its own resources exist")
    need(m1, "bool ready() const { return raster && condition && vertical && m25_analyse && m25_guard && m25_tiles && m25_stats && m25_readback && soft_depth && constants; }",
         "M4 failure never disables stereo")
    need(dx, "m1_raw_srv_,m2_fovea_srv_,settings.m4_fovea_grid);", "writer receives the setting")
    need(dx, "D3D12_ROOT_PARAMETER params[9]{};", "two new root tables")
    need(dx, "D3D12_ROOT_SIGNATURE_DESC desc{9, params,", "root signature count")
    need(dx, "hd.NumDescriptors = 14;", "heap grew by two")
    need(dx, "m4_table.ptr+=UINT64(12)*srv_descriptor_increment_;", "compute table at heap slot 12")
    need(dx, "m4_field.ptr+=UINT64(12)*srv_descriptor_increment_;", "raster table at heap slot 12")
    need(dx, "cmd->Dispatch(m1_.m4_rows,1,1);", "row dispatch")
    need(dx, "cmd->Dispatch(m1_.m4_columns,1,1);", "vertical dispatch")
    # Heap slot 12/13 are the two descriptors created right after slot 11 (stats UAV).
    tail = dx[dx.find("&stats_uav,desc_cpu);"):]
    if not (tail.find("// [12] t8 M4 fovea field") < tail.find("// [13] u5 M4 fovea field") < tail.find("direct_xr_rtv_cpu_=rtv_cpu_start_;")):
        failures.append("M4 descriptors are not slots 12/13")

    # Settings: designated-initializer order must follow DuoViewConfig declaration order (MSVC C7560).
    struct = cfg[cfg.find("struct Settings {"):]
    struct = struct[:struct.find("\n};")]
    struct = re.sub(r"//[^\n]*", "", struct)
    declared = re.findall(r"(\w+)\{[^{};]*\};", struct)
    start = vrcpp.find("uevr::duoview::Settings candidate{")
    block = vrcpp[start:vrcpp.find("\n    };", start)]
    used = re.findall(r"(?:^|[\s,{])\.([A-Za-z_]\w*)=(?!=)", block, re.M)
    if len(declared) < 30 or len(used) < 30:
        failures.append(f"settings parse failed: declared={len(declared)} used={len(used)}")
    if "m4_fovea_grid" not in declared:
        failures.append("Settings struct lacks m4_fovea_grid")
    pos = [declared.index(n) for n in used if n in declared]
    if pos != sorted(pos):
        bad = [used[i] for i in range(1, len(pos)) if pos[i] < pos[i-1]]
        failures.append(f"designated initializers out of declaration order near: {bad[:3]}")
    need(vrcpp, ".m2_fovea_depth=m_duo_m2_fovea_depth->value() || m_duo_m4_fovea_grid->value(),", "M4 turns fine depth on")
    need(vrcpp, ".m25_fine_mode=m_duo_m4_fovea_grid->value() ? 1u :", "M4 uses content-checked delivery")
    need(vrcpp, "current.m4_fovea_grid==candidate.m4_fovea_grid &&", "change detection")
    need(vrcpp, "m_duo_m4_fovea_grid->value()=false;", "reset to default")
    need(vrcpp, "m_duo_m4_fovea_grid->draw(", "menu entry")
    need(vrhpp, 'generate_name("DuoM4FoveaDepthGrid"),false)', "persisted key, default OFF")
    need(vrhpp, "*m_duo_m4_fovea_grid,", "saved with the other DuoView options")

    if failures:
        print("\n".join("FAIL " + f for f in failures))
        raise SystemExit(1)
    print("PASS: M4 generated contracts (layout, registers, wiring, settings order)")


if __name__ == "__main__":
    main()
