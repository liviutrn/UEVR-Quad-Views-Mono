#!/usr/bin/env python3
"""Reserve current DuoView producer copies until their Present consumer.

Apply after the CI31 overlay. This repairs lifetime, not semantic eye/stage
identity. No old depth becomes eligible for a newer color interval.
"""
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1]).resolve()
here = Path(__file__).resolve().parents[3]
target = root / 'src/mods/vr/d3d12/StockDibrDepth.hpp'
text = target.read_text(encoding='utf-8-sig')
old = 'auto it = std::find_if(slots.begin(), slots.end(), [&](const Slot& s) { return retire_ready(s, fence.Get()); });'
new = '''auto it = std::find_if(slots.begin(), slots.end(), [&](const Slot& s) {
                return capture_slot_reusable(retire_ready(s, fence.Get()),
                    duoview_source_sizes[0]!=0, s.texture.Get()!=nullptr, s.epoch, epoch);
            });'''
if text.count(old) != 1:
    raise RuntimeError('Capture retention: producer slot anchor missing/ambiguous')
text = text.replace(old, new, 1)
anchor = '#include "DepthPolicy.hpp"'
if text.count(anchor) != 1:
    raise RuntimeError('Capture retention: header anchor missing/ambiguous')
text = text.replace(anchor, anchor + '\n#include "CaptureSlotPolicy.hpp"', 1)
shutil.copyfile(here / 'stock_dibr/CaptureSlotPolicy.hpp', target.with_name('CaptureSlotPolicy.hpp'))
target.write_text(text, encoding='utf-8', newline='')
print('Capture retention fixed: current interval copies stay immutable until consumer retirement.')
