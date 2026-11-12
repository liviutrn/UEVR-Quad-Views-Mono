#!/usr/bin/env python3
"""Liviu's standard UEVR defaults (from his config.txt, 9 Nov 2026).

Only the built-in DEFAULT values change: a saved config.txt still wins. The
script edits each option's default argument in the generated backend by name,
so it works on any branch that has these options; every name must be found
exactly once (a missing/duplicated option fails the build).
"""
from pathlib import Path
import re
import sys

# (config name without prefix as written in code, value)
DEFAULTS = [
    # Framework / UI
    ('generate_name("AdvancedMode")', 'true'),        # FrameworkConfig_AdvancedMode
    ('generate_name("MenuOpen")', 'false'),           # FrameworkConfig_MenuOpen
    ('"Frontend_RequestedRuntime"', '"openxr_loader.dll"'),
    ('"UI_Distance"', '10.0f'),
    ('"UI_Size"', '10.0f'),
    ('"UI_Framework_Distance"', '10.0f'),
    ('"UI_Framework_Size"', '8.0f'),
    # VR basics
    ('generate_name("CameraForwardOffset")', '15.0f'),
    ('generate_name("CameraUpOffset")', '10.0f'),
    ('generate_name("DecoupledPitch")', 'true'),
    ('generate_name("WorldScale")', '0.85f'),
    ('generate_name("RecenterViewKey")', '226'),        # the <> key next to left Shift
    ('generate_name("ResetStandingOriginKey")', '226'),
    ('generate_name("XYZHeadScalingEnabled")', 'true'),
    ('generate_name("XYZHeadScaleX")', '3.0f'),
    ('generate_name("XYZHeadScaleZ")', '1.5f'),
    # DuoView Mono (ID6) — Liviu's known mono setup.
    ('"OpenXR_MonoEyeAlignmentEnabled"', 'true'),
    ('"OpenXR_MonoEyeAlignmentPercent"', '-1.5f'),
    ('generate_name("DuoViewSameImageBothEyes")', 'true'),
    ('generate_name("DuoViewSharpPeriphery")', 'false'),
    # TriView (ID7)
    ('generate_name("QuadViewContextScale")', '.30f'),
    ('generate_name("QuadViewFeather")', '.10f'),
    ('generate_name("QuadViewFocusWidth")', '.60f'),
    ('generate_name("QuadViewFocusHeight")', '.60f'),
    ('generate_name("QuadViewGazeBreakout")', '.25f'),
    ('generate_name("QuadViewGazeMicroGain")', '.25f'),
    ('generate_name("QuadViewLegacyInwardFeather")', 'false'),
    ('generate_name("QuadViewSharpenLinkEyes")', 'false'),
    ('generate_name("QuadViewSharpenRight")', '10.f'),
    ('generate_name("QuadViewSharpenRightMaxChange")', '.40f'),
]

# Position of the default argument after the name, per option kind.
DEFAULT_ARG = {'ModToggle': 0, 'ModFloat': 0, 'ModSlider': 2, 'ModInt32': 0, 'ModSliderInt32': 2,
               'ModCombo': 1, 'ModKey': 0, 'ModString': 0}


def split_args(text):
    """Split top-level comma-separated arguments of text (no outer parens)."""
    args, depth, cur, quote = [], 0, '', False
    for ch in text:
        if ch == '"' and not cur.endswith('\\'):
            quote = not quote
        if not quote:
            if ch in '({[': depth += 1
            elif ch in ')}]': depth -= 1
            elif ch == ',' and depth == 0:
                args.append(cur); cur = ''; continue
        cur += ch
    if cur.strip(): args.append(cur)
    return args


def set_default(source, needle, value):
    hits = [m for m in re.finditer(r'(Mod\w+)::create\(\s*' + re.escape(needle), source)]
    if len(hits) != 1:
        raise RuntimeError(f'Liviu default {needle}: {len(hits)} declarations')
    m = hits[0]; kind = m.group(1)
    if kind not in DEFAULT_ARG:
        raise RuntimeError(f'Liviu default {needle}: unsupported kind {kind}')
    start = m.end()  # just after the name
    depth, i = 1, source.index('(', m.start()) + 1
    while depth:
        depth += (source[i] == '(') - (source[i] == ')'); i += 1
    close = i - 1
    rest = source[start:close]
    args = split_args(rest.lstrip(',')) if rest.strip() else []
    if needle.startswith('generate_name(') and args and args[0].strip() == ')':
        args = args[1:]
    # generate_name("X") leaves its own ')' at the start of rest.
    prefix = ''
    if rest.startswith(')'):
        prefix, rest = ')', rest[1:]
        args = split_args(rest.lstrip(',')) if rest.strip() else []
    idx = DEFAULT_ARG[kind]
    if idx > len(args):
        raise RuntimeError(f'Liviu default {needle}: missing earlier arguments for {kind}')
    if idx == len(args):
        args.append(' ' + value)
    else:
        args[idx] = ' ' + value
    new = prefix + ',' + ','.join(args)
    return source[:start] + new + source[close:]


def main():
    mods = Path(sys.argv[1]) / 'src/mods'
    files = [p for p in mods.rglob('*.hpp')] + [p for p in mods.rglob('*.cpp')]
    texts = {p: p.read_text(encoding='utf-8') for p in files}
    for needle, value in DEFAULTS:
        owners = [p for p, s in texts.items() if re.search(r'Mod\w+::create\(\s*' + re.escape(needle), s)]
        if len(owners) != 1:
            raise RuntimeError(f'Liviu default {needle}: found in {len(owners)} files')
        texts[owners[0]] = set_default(texts[owners[0]], needle, value)
    # Rendering method: TriView (ID 7) through the same loader a saved config uses.
    p = mods / 'vr/RenderingMethodSetting.hpp'
    s = texts[p]
    old = 'm_selection.initialize(defaults ? 0 : cfg.get<int32_t>(m_name).value_or(requested_value()));'
    if s.count(old) != 1:
        raise RuntimeError('Liviu default RenderingMethod: loader anchor not found')
    s = s.replace(old, 'm_selection.initialize(defaults ? uevr::mono::quadview_method_id : '
                       'cfg.get<int32_t>(m_name).value_or(uevr::mono::quadview_method_id));')
    old = 'if (ImGui::Button("Reset to default")) { request(0); changed = true; }'
    if s.count(old) != 1:
        raise RuntimeError('Liviu default RenderingMethod: reset anchor not found')
    texts[p] = s.replace(old, 'if (ImGui::Button("Reset to default")) { request(uevr::mono::quadview_method_id); changed = true; }')
    for p, s in texts.items():
        if p.read_text(encoding='utf-8') != s:
            p.write_text(s, encoding='utf-8', newline='\n')
    print(f'Applied Liviu defaults: {len(DEFAULTS)} options + rendering method TriView (7)')


if __name__ == '__main__':
    main()
