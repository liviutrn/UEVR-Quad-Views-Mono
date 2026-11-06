#!/usr/bin/env python3
"""B18 depth lifetime fixes; apply after B17 + B18 core, before resources.

Capture remains explicitly approximate: the current adapter cannot authenticate
an NGX evaluation to a UE source packet. Do not reintroduce fabricated ownership.
"""
from pathlib import Path
import sys

def one(s, old, new, label):
    if s.count(old) != 1:
        raise RuntimeError(f"B18 depth {label}: expected one anchor, got {s.count(old)}")
    return s.replace(old, new, 1)

def hook_header(s):
    if "depth_not_before" in s: raise RuntimeError("B18 packet bound already applied")
    return one(s,
        '    struct QuadViewSourcePacket {\n',
        '    struct QuadViewSourcePacket {\n'
        '        // Temporal exclusion bound only; not proof of exact NGX source ownership.\n'
        '        std::chrono::steady_clock::time_point depth_not_before{std::chrono::steady_clock::now()};\n',
        'packet birth bound')

def consumer(s):
    return one(s,
        'uevr::quadview::ngx::PeripheryDepth::self().latest()',
        'uevr::quadview::ngx::PeripheryDepth::self().latest_approximate_since(packet->depth_not_before)',
        'bounded approximate selection')

def vr(s):
    return one(s,
        '                m_quadview_depth_reproject->draw("Periphery depth reprojection (stereo periphery from DLSS depth)");\n',
        '                m_quadview_depth_reproject->draw("Periphery depth reprojection (approximate DLSS depth)");\n'
        '                if (ImGui::IsItemHovered()) ImGui::SetTooltip("Depth is matched by size and capture time, not exact scene identity. Fast motion may show mismatch.");\n',
        'truthful depth status')

def main():
    if len(sys.argv)!=2:
        raise SystemExit('Usage: apply_triview_b18_depth.py <backend>')
    root=Path(sys.argv[1])/'src/mods'
    source=Path(__file__).resolve().parent
    paths={root/'vr/FFakeStereoRenderingHook.hpp':hook_header,
           root/'vr/D3D12Component.cpp':consumer,root/'VR.cpp':vr}
    results={p: fn(p.read_text(encoding='utf-8')) for p,fn in paths.items()}
    target=root/'vr/QuadViewNgxDepth.hpp'
    if 'latest_approximate_since' in target.read_text(encoding='utf-8'):
        raise RuntimeError('B18 depth already applied')
    results[target]=(source/'QuadViewNgxDepthB18.hpp').read_text(encoding='utf-8')
    results[root/'vr/QuadViewDepthIdentity.hpp']=(source/'QuadViewDepthIdentity.hpp').read_text(encoding='utf-8')
    for p,value in results.items(): p.write_text(value,encoding='utf-8',newline='\n')
    print('B18 depth: recording epochs, Reset/submit sequencing, retired pool pruning; approximate capture disclosed')

if __name__=='__main__': main()
