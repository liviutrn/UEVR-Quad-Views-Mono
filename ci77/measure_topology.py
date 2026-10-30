import sys,json,zipfile
from pathlib import Path
import numpy as np
sys.path.insert(0,'ci75_work/ci75');import analyze_capture as a
rows=[]
for archive in sorted(Path('upload').glob('diagnostic_14744*_part*.zip')):
 with zipfile.ZipFile(archive) as z:
  m=json.loads(z.read('manifest.json'))
  for f in m['frames']:
   for p in f['planes']:
    if p['name']!='full_depth_right':continue
    raw,_=a.decode_native(a.decode_png_rows(z.read(p['file']),p),p)
    dep=np.where(raw>1e-9,1/np.maximum(raw,1e-9),-1)
    h,w=dep.shape; attached=np.zeros((h,w),bool)
    corners=[dep[:-1,:-1],dep[:-1,1:],dep[1:,:-1],dep[1:,1:]]
    ok=[]
    for ids in ((0,1,2),(1,3,2)):
     vals=np.stack([corners[i] for i in ids]);lo=vals.min(0);hi=vals.max(0)
     yes=(lo>.01)&(hi<1e8)&((hi-lo)<=2+.025*lo);ok.append(yes)
    attached[:-1,:-1]|=ok[0];attached[:-1,1:]|=ok[0]|ok[1]
    attached[1:,:-1]|=ok[0]|ok[1];attached[1:,1:]|=ok[1]
    valid=(dep>.01)&(dep<1e8)
    # Exclude image border; count measured points no accepted triangle can use.
    valid[[0,-1],:]=False;valid[:,[0,-1]]=False
    rows.append({'frame':f['index'],'valid_points':int(valid.sum()),'unrepresented_points':int((valid&~attached).sum()),'fraction_unrepresented':float((valid&~attached).sum()/valid.sum()),'triangle_reject_fraction':float(1-np.stack(ok).mean())})
Path('ci77_astra_work/topology_measurements.json').write_text(json.dumps(rows,indent=2))
print(json.dumps(rows,indent=2))
