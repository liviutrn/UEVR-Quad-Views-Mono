#!/usr/bin/env python3
"""B42 contracts on the generated backend: VRAM guard, snapping, rebuild pause,
low-resolution start (never saved), VRAM logs."""
from pathlib import Path
import sys


def need(text, snippet, what):
    if snippet not in text:
        raise SystemExit(f"B42 contract failed: {what}")


root = Path(__file__).resolve().parent
need((root / 'QuadViewGeometry.hpp').read_text(), 'void cancel_latch()', 'ResizeGate cancel_latch')
need((root / 'QuadViewGeometry.hpp').read_text(), 'cooldown_ms_ == 0 || now_ms - published_ms_ >= cooldown_ms_', 'ResizeGate cooldown')
mods = Path(sys.argv[1]) / 'src/mods'
vr = (mods / 'VR.cpp').read_text()
vh = (mods / 'VR.hpp').read_text()
xr = (mods / 'vr/runtimes/OpenXR.cpp').read_text()
xh = (mods / 'vr/runtimes/OpenXR.hpp').read_text()
dx = (mods / 'vr/D3D12Component.cpp').read_text()
fh = (mods / 'vr/FFakeStereoRenderingHook.cpp').read_text()
need((mods / 'vr/TriViewVramGuard.hpp').read_text(), 'bytes_per_source_pixel = 100', 'guard header copied')
need((mods / 'vr/QuadViewGeometry.hpp').read_text(), 'void cancel_latch()', 'generated geometry carries B42 gate')
need(vr, 'm_triview_resize_gate.set_cooldown_ms(1500);', 'gate pause')
need(vr, 'm_triview_resize_gate.cancel_latch();', 'refusal drops latch')
need(vr, '[TriView][VRAM] resize REFUSED', 'refusal log')
need(vr, 'requested.crop_width=uevr::quadview::vram::snap_fraction(', 'snapping')
need(vr, 'void VR::service_triview_low_start()', 'low start service')
need(vr, '[TriView][Build] B42.1', 'build identity')
need(vr, 'm_rendering_method->requested_value() == RenderingMethod::QUAD_VIEWS_STEREO)) {', 'low start sees saved ID7 request')
need(vh, 'QuadViewB42VramLimitPercent', 'limit option')
need(vh, '*m_triview_b42_vram_limit, *m_triview_b42_low_start, *m_triview_b42_low_start_scale,', 'options saved')
need(xh, 'static inline std::atomic<float> triview_warmup_scale{0.f};', 'warm-up scale')
need(xr, 'return this->get_width_for_scale(warm); // B42', 'get_width warm-up')
need(xr, 'return this->get_height_for_scale(warm); // B42', 'get_height warm-up')
need(xr, 'bool OpenXR::finish_triview_warmup(const char* reason)', 'one-shot switch')
need(dx, 'vr->service_triview_low_start(); // B42', 'present-thread service')
need(dx, 'depth pool {} slots {} MB', 'VRAM log with depth pool')
need(fh, 'vram_used={} MB budget={} MB', 'VRAM on build/publish')
# The saved resolution must never be written by B42.
if 'resolution_scale->value() =' in xr.split('bool OpenXR::finish_triview_warmup', 1)[1].split('uint32_t OpenXR::get_width()', 1)[0]:
    raise SystemExit('B42 contract failed: warm-up switch writes the saved resolution scale')
print('B42 contracts: ok')
