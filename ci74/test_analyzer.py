import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from PIL import Image, ImageDraw
from analyze_sequence import analyze, save_report

class SequenceTests(unittest.TestCase):
    def test_still_vs_jitter(self):
        with tempfile.TemporaryDirectory() as d:
            fn=Path(d)/'synthetic.zip'
            frames=[]
            with zipfile.ZipFile(fn,'w') as z:
                for i in range(8):
                    frames.append({'index':i,'time_ms':i*33,'metadata':'eye0Position=0,0,0, eye1Position=6,0,0,'})
                    for role in ['xr_left','xr_right','source_left','source_right']:
                        im=Image.new('RGB',(80,80),'black'); draw=ImageDraw.Draw(im)
                        shift=i%2*3 if role=='xr_right' else 0
                        draw.rectangle((30+shift,10,50+shift,70),fill='white')
                        b=io.BytesIO();im.save(b,'JPEG',quality=90)
                        z.writestr(f'frames/f{i}_{role}.jpg',b.getvalue())
                z.writestr('manifest.json',json.dumps({'schema':'duoview-sequence-1','frames':frames,'frames_recorded':8,'truncated_by_size':False}))
            data=analyze(fn)
            assert data['roles']['xr_left']['edge_change_mean_median']==0
            assert data['roles']['xr_right']['edge_change_mean_median']>0.02
            assert data['pose']['position_stationary']
            report=save_report(data,Path(d)/'report.json');assert report.exists()
            assert (Path(d)/'report_xr_right_temporal_heat.png').exists()

if __name__=='__main__': unittest.main()
