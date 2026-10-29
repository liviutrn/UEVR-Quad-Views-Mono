from pathlib import Path
import hashlib,json,sys
source=Path(__file__).resolve().parent
backend=Path(sys.argv[1]).resolve()
contract=json.loads((source/'source_contract.json').read_text())
pending=[]
for rel,expected in contract.items():
    relative=Path(rel)
    if '..' in relative.parts or relative.is_absolute():raise RuntimeError('Unsafe public source path')
    current=backend/relative;replacement=(source/'production'/relative).read_bytes()
    if hashlib.sha256(replacement).hexdigest()!=expected['after_lf_sha256']:raise RuntimeError('Overlay integrity: '+rel)
    existing=hashlib.sha256(current.read_bytes().replace(b'\r\n',b'\n')).hexdigest() if current.exists() else None
    if existing==expected['after_lf_sha256']:continue
    if existing!=expected['before_lf_sha256']:raise RuntimeError('CI50 baseline changed: '+rel)
    pending.append((current,replacement))
for target,raw in pending:
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
print('CI51 final public source overlay verified:',len(contract),'files,',len(pending),'replaced')
