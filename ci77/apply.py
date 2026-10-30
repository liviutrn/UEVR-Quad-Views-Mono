"""Apply CI77 only to exact verified generated CI76 production sources."""
from pathlib import Path
import hashlib,json,sys

def digest(s):return hashlib.sha256(s.encode()).hexdigest()
def apply(root):
 root=Path(root);here=Path(__file__).resolve().parent;spec=json.loads((here/'patches.json').read_text());pending={}
 for rel,change in spec['patches'].items():
  p=root/rel;s=p.read_text()
  if digest(s)!=change['before_sha256']:raise RuntimeError('CI77 baseline hash mismatch: '+rel)
  for b in reversed(change['blocks']):
   if s.count(b['old'])!=1:raise RuntimeError('CI77 nonunique source anchor: '+rel)
   s=s.replace(b['old'],b['new'])
  if digest(s)!=change['after_sha256']:raise RuntimeError('CI77 output hash mismatch: '+rel)
  pending[p]=s
 for item in spec['added']:pending[root/item['target']]=(here/item['source']).read_text()
 for p,s in pending.items():p.parent.mkdir(parents=True,exist_ok=True);p.write_text(s)
 print('CI77 integrated: stabilized per-eye guides, actual processed preview, high-resolution LEFT geometry, raw+stable recorder')
if __name__=='__main__':apply(sys.argv[1])
