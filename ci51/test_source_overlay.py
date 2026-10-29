from pathlib import Path
import hashlib,json,subprocess,sys,tempfile,shutil
source=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='ci51-overlay-test-') as tmp:
    test=Path(tmp);overlay=test/'overlay';backend=test/'backend';overlay.mkdir();backend.mkdir()
    shutil.copyfile(source/'apply.py',overlay/'apply.py')
    data={'src/test.cpp':{'before_lf_sha256':hashlib.sha256(b'old\nsource\n').hexdigest(),'after_lf_sha256':hashlib.sha256(b'new\nsource\n').hexdigest()}}
    (overlay/'production/src').mkdir(parents=True);(backend/'src').mkdir()
    (overlay/'source_contract.json').write_text(json.dumps(data))
    (overlay/'production/src/test.cpp').write_bytes(b'new\r\nsource\r\n');(backend/'src/test.cpp').write_bytes(b'old\r\nsource\r\n')
    subprocess.run([sys.executable,str(overlay/'apply.py'),str(backend)],check=True)
    assert (backend/'src/test.cpp').read_bytes()==b'new\nsource\n'
    subprocess.run([sys.executable,str(overlay/'apply.py'),str(backend)],check=True)
    (overlay/'production/src/test.cpp').write_bytes(b'new\r\nTAMPERED\r\n')
    fail=subprocess.run([sys.executable,str(overlay/'apply.py'),str(backend)],capture_output=True,text=True)
    assert fail.returncode and 'Overlay integrity' in fail.stderr
    assert (backend/'src/test.cpp').read_bytes()==b'new\nsource\n'
print('PASS: real overlay handles CRLF inputs/outputs, is idempotent, rejects content tampering without mutation')
