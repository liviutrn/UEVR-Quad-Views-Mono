#!/usr/bin/env python3
"""Liviu's DuoView tab defaults (from his config.txt after the #379 headset test, 19 Nov 2026).

Runs AFTER all DuoView overlays (goal D included) and their generated-source contract tests, so every
DuoView option exists. Same rule as apply_liviu_defaults.py: only built-in DEFAULT values change; a saved
config.txt still wins. Every option must be declared exactly once in the generated backend.

Changes vs his saved config (his #379 verdict, DECISIONS 2026-11-19): fovea search steps 6 (index 2),
periphery search steps 2 (index 6), periphery VRS 4x4 (index 6), warp bypass diagnostic Off, history
motion source Head pose (index 0).
"""
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_liviu_defaults import set_default  # noqa: E402

# Option name (as in config.txt without the "VR_" prefix) -> config value.
DEFAULTS = {
    'DuoDepthSmoothClose': '0.000000', 'DuoDepthSmoothFar': '1.000000',
    'DuoEdgeHistory': '0.700000', 'DuoEdgeHistoryReachPixels': '8.188000',
    'DuoFastStereoRaster': 'true', 'DuoFillBlurPixels': '1.200000', 'DuoFillHistory': '0.650000',
    'DuoFoveaBackgroundFill': '3', 'DuoFoveaDepthGridSize': '1', 'DuoFoveaDepthHistory': '1',
    'DuoFoveaHistoryConfirm': '6', 'DuoFoveaHistoryMotion': '0', 'DuoFoveaHistoryStillLimit': '31.305000',
    'DuoFoveaJitterDirection': '0',
    'DuoFoveaSearchSteps': '2',        # "6"
    'DuoPeripherySearchSteps': '6',    # "2" (saved config still had 0 = "8")
    'DuoPeripheryVrsRate': '6',        # "4x4"
    'DuoWarpBypassDiag': 'false',
    'DuoHaloBgFullMeters': '0.100000', 'DuoHaloBgOffMeters': '4.466000',
    'DuoM21FoveaDepth': 'true', 'DuoM21JitterCorrect': 'false',
    'DuoM23UnlinkedWide': 'false', 'DuoM23WideLeft': '0.500000', 'DuoM23WideRight': '2.500000',
    'DuoM23WideStrength': '1.000000',
    'DuoM24DistanceFade': 'true', 'DuoM24FadeFarM': '21.073000', 'DuoM24FadeNearM': '3.991000',
    'DuoM24NormalFarPercent': '25.625000', 'DuoM24VerticalTaper': '0.000000', 'DuoM24WideFarPercent': '24.375000',
    'DuoM25DepthDebug': '0.000000', 'DuoM25FineMode': '0.000000',
    'DuoM2IndependentSharpen': 'false', 'DuoM2LeftSharpen': '4.250000', 'DuoM2RightSharpen': '15.875000',
    'DuoM3BackgroundFill': 'false', 'DuoM3JitterMode': '0', 'DuoM3OcclusionSharpness': '0.500000',
    'DuoM3PerEyeEdges': 'false', 'DuoM4FoveaDepthGrid': 'true',
    'DuoM5LeftMaxSharpness': '0.102000', 'DuoM5RightMaxSharpness': '0.400000',
    'DuoM8DistanceEdges': 'true', 'DuoM8EdgeFar': '0.497000', 'DuoM8EdgeNear': '0.000000',
    'DuoM8EndMeters': '10.761000', 'DuoM8FillFar': '0.000000', 'DuoM8FillNear': '0.000000',
    'DuoM8StartMeters': '0.250000', 'DuoM9PerEyeFar': '0.000000', 'DuoM9PerEyeNear': '0.000000',
    'DuoStereoDepthSchemaV2': 'true', 'DuoStereoLegacyCurveV2': 'false',
    'DuoViewB40AmbientInsidePx': '96.000000', 'DuoViewB40AmbientRadiusPx': '128.000000',
    'DuoViewB40TemporalPreset': '2',
    'DuoViewCropGuard': '0.050000', 'DuoViewCropHeight': '0.600000', 'DuoViewCropStability': 'true',
    'DuoViewCropWidth': '0.600000', 'DuoViewDebugBorder': 'false', 'DuoViewDebugSource': '0',
    'DuoViewDirectXROutput': 'false', 'DuoViewEyeTracking': 'true', 'DuoViewFOVReapplyKey': '-1',
    'DuoViewFeather': '0.100000', 'DuoViewFitSourceProjection': 'true', 'DuoViewFocusBrightness': '1.000000',
    'DuoViewFocusCornerGain': '0.148000', 'DuoViewFocusLift': 'true', 'DuoViewFocusLiftOnset': '0.469400',
    'DuoViewFocusLiftPower': '0.924000', 'DuoViewFoveaSourceView': '0', 'DuoViewFovealDensity': '1.000000',
    'DuoViewGazeBreakout': '0.250000', 'DuoViewGazeHoldMs': '350', 'DuoViewGazeMicroGain': '0.253000',
    'DuoViewGazeOffsetX': '0.000000', 'DuoViewGazeOffsetY': '0.050000', 'DuoViewGazeReacquireSamples': '2',
    'DuoViewGazeRelockSamples': '3', 'DuoViewGazeStillness': '0.008000',
    'DuoViewGlamaryeExtraWide': 'false', 'DuoViewGlamaryeFoveaMaxChange': '0.100000',
    'DuoViewGlamaryeFoveaStrength': '1.000000', 'DuoViewGpuTiming': 'true', 'DuoViewNativeFixSamePass': 'true',
    'DuoViewPeripheralScale': '0.300000', 'DuoViewQuantizationPixels': '2', 'DuoViewSameImageBothEyes': 'true',
    'DuoViewSeamColorStrength': '1.000000', 'DuoViewSeamInwardFeatherPx': '12.000000', 'DuoViewSeamMatch': 'true',
    'DuoViewSeamMaxGain': '0.250000', 'DuoViewSeamOutwardReachPx': '576.700012', 'DuoViewSeamStrength': '1.000000',
    'DuoViewSharpPeriphery': 'false', 'DuoViewSkipDepthSwapchain': 'true', 'DuoViewStereoEdgeSoftness': '0.990000',
    'DuoViewStereoNearMeters': '0.512000', 'DuoViewStereoStrength': '1.000000', 'DuoViewSyntheticStereo': 'true',
}

INT_KINDS = {'ModCombo', 'ModInt32', 'ModSliderInt32', 'ModKey'}
FLOAT_KINDS = {'ModSlider', 'ModFloat'}


def literal(kind, name, value):
    if kind == 'ModToggle':
        if value not in ('true', 'false'):
            raise RuntimeError(f'{name}: toggle value {value!r}')
        return value
    if kind in INT_KINDS:
        return str(int(float(value)))
    if kind in FLOAT_KINDS:
        v = repr(float(value))
        return v + 'f'
    raise RuntimeError(f'{name}: unsupported kind {kind}')


def main():
    mods = Path(sys.argv[1]) / 'src/mods'
    files = list(mods.rglob('*.hpp')) + list(mods.rglob('*.cpp'))
    texts = {p: p.read_text(encoding='utf-8') for p in files}
    for name, value in DEFAULTS.items():
        needle = f'generate_name("{name}")'
        pat = re.compile(r'(Mod\w+)::create\(\s*' + re.escape(needle))
        owners = [(p, pat.findall(s)) for p, s in texts.items() if pat.search(s)]
        if len(owners) != 1 or len(owners[0][1]) != 1:
            raise RuntimeError(f'Liviu DuoView default {name}: {sum(len(o[1]) for o in owners)} declarations')
        p, kinds = owners[0]
        texts[p] = set_default(texts[p], needle, literal(kinds[0], name, value))
        print(f'  {name} = {literal(kinds[0], name, value)} ({kinds[0]})')
    for p, s in texts.items():
        if p.read_text(encoding='utf-8') != s:
            p.write_text(s, encoding='utf-8', newline='\n')
    print(f'Applied Liviu DuoView defaults: {len(DEFAULTS)} options')


if __name__ == '__main__':
    main()
