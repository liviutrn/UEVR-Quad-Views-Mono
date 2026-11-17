#!/usr/bin/env python3
"""Generated-source contracts for the edge toggle (Off / K3D10TS16 / K23D10TS16)."""
import importlib.util
import sys
from pathlib import Path


def main():
    backend, shaders = Path(sys.argv[1]), Path(sys.argv[2])
    spec = importlib.util.spec_from_file_location('edge_toggle', Path(__file__).with_name('apply_duoview_edge_toggle.py'))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    hlsl = (shaders / 'DuoViewM1Stereo.hlsl').read_text(encoding='utf-8')
    off = mod.strip_k(hlsl)
    for token in ('M10Edge', 'M10Hist', 'M10History', 'M10FoveaColor', 'M10Encode', 'iteration<16u', 'M10Ramp'):
        if token in off:
            raise SystemExit(f'K token leaks into Off shader text: {token}')
        if token not in hlsl:
            raise SystemExit(f'K token missing: {token}')
    if 'iteration<8u' not in off or off.count('const uint slices=M3Flags.x>.5 ? 2u : 1u;') != 2:
        raise SystemExit('Off bisection/vertical slices changed')
    vr = backend / 'src/mods/vr'
    m1 = (vr / 'DuoViewM1D3D12.hpp').read_text(encoding='utf-8')
    comp = (vr / 'DuoViewD3D12.hpp').read_text(encoding='utf-8')
    cfg = (vr / 'DuoViewConfig.hpp').read_text(encoding='utf-8')
    vrh = (backend / 'src/mods/VR.hpp').read_text(encoding='utf-8')
    vrc = (backend / 'src/mods/VR.cpp').read_text(encoding='utf-8')
    need = {
        'm1': (m1, ['sizeof(M1Constants) == 608', 'float m10_edge[4]{}', 'm1_raster_k_bytecode',
                    'm4_condition_k_bytecode', 'k_grid=k_requested', 'p.w==m4_columns && p.h==m4_rows && p.mode==edge_mode',
                    'struct DuoEdgeHistoryKey', 'distance_edges && edge_reach_px>=10.f && k_pipelines()']),
        'compositor': (comp, ['ComPtr<ID3D12Resource> edge_history;', 'settings.stereo_edge_mode',
                              'm1_.k_coarse ? m1_.raster_k.Get() : m1_.raster.Get()',
                              'm1_.k_m4 ? m1_.m4_condition_k.Get() : m1_.m4_condition.Get()',
                              '(b40_active || (m1_active && m1_.k_m4))',
                              'DuoEdgeHistoryKey edge_key{};', 'edge_hist_recorded_=!m4_probe_skip;',
                              'b40_history_->edge_key=m1_.k_hist_next;', 'b40_history_->edge_key.valid=false;',
                              'DXGI_FORMAT_R32G32_UINT', 'report_edge_status(']),
        'config': (cfg, ['uint32_t stereo_edge_mode{0};', 'out.stereo_edge_mode=(std::min)(requested.stereo_edge_mode,2u);',
                   'duo_edge_status()', 'duo_edge_status_text(']),
        'vr.hpp': (vrh, ['generate_name("DuoStereoEdgeMode")', '*m_duo_edge_mode,']),
        'vr.cpp': (vrc, ['m_duo_edge_mode->draw(', '.stereo_edge_mode=uint32_t(', 'current.stereo_edge_mode==candidate.stereo_edge_mode',
                    'uevr::duoview::duo_edge_status_text(']),
    }
    for name, (text, tokens) in need.items():
        for t in tokens:
            if text.count(t) < 1:
                raise SystemExit(f'{name}: missing {t}')
    # Off pipelines must stay the original ones whenever K is not requested.
    if comp.count('m1_.condition.Get()') != 2 or 'm1_.vertical.Get()' not in comp:
        raise SystemExit('Off coarse pipeline selection changed')
    print('edge toggle generated contracts PASS')


if __name__ == '__main__':
    main()
