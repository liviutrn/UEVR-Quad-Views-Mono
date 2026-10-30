"""Independent decoder checks exact GPU bits and complete multi-part retention."""
import io
import json
import sys
import zipfile
from pathlib import Path
import numpy as np
from PIL import Image

root=Path(sys.argv[1])
colors=np.frombuffer((root/'input_color.bin').read_bytes(),dtype=np.uint8).reshape(256,1024,4)
depth=np.frombuffer((root/'input_depth.bin').read_bytes(),dtype=np.uint8).reshape(256,512,4)
files=sorted(root.glob('diagnostic_*75001_part*.zip'))
assert len(files)>=2,'actual multi-part recorder path not exercised'
frames={};checks=0
for file in files:
    assert file.stat().st_size<=20*1024*1024,'part exceeds upload limit'
    with zipfile.ZipFile(file) as archive:
        assert archive.testzip() is None,'ZIP CRC failure'
        manifest=json.loads(archive.read('manifest.json'))
        assert manifest['part_count']==len(files)
        assert manifest['total_encoded_frames']==24
        assert manifest['truncated_by_size'] is False
        assert manifest['capture_complete'] is True
        for frame in manifest['frames']:
            assert frame['index'] not in frames,'duplicate global frame index'
            frames[frame['index']]=frame
            for plane in frame['planes']:
                image=np.asarray(Image.open(io.BytesIO(archive.read(plane['file']))).convert('RGBA'))
                row_bytes=plane['row_bytes'];width=plane['width'];height=plane['height']
                decoded=image.reshape(height,-1)[:,:row_bytes].reshape(height,width,4)
                x0,y0,x1,y1=plane['box']
                reference=depth if plane['name'].startswith('depth') else colors
                expected=reference[y0:y1,x0:x1,:]
                assert np.array_equal(decoded,expected),(frame['index'],plane['name'],'GPU bit mismatch')
                checks+=decoded.size
assert sorted(frames)==list(range(24)),'frames were discarded during splitting'
print(f'PASS independent ZIP reader: {len(files)} parts, ALL 24 frames retained, {checks} bytes bit-exact including NaN/Inf/subnormal/zero-alpha patterns')

import subprocess
subprocess.run([sys.executable,str(Path(__file__).with_name('analyze_capture.py')),
                *map(str,files),'--out',str(root/'analysis')],check=True)
print('PASS analyzer accepts actual recorder schema and regenerates viewable diagnostics')
