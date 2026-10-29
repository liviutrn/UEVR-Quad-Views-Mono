"""Apply CI69 manual NGX-only source patch after CI67 verified overlay."""
from pathlib import Path
import sys,base64,gzip,hashlib,subprocess,tempfile
if len(sys.argv)!=2:
    raise SystemExit("usage: python workspace/ci69/apply.py BACKEND_ROOT")
base=Path(__file__).resolve().parent
backend=Path(sys.argv[1]).resolve()
patch=gzip.decompress(base64.b64decode((base/"payload.b64").read_text().strip()))
digest=hashlib.sha256(patch).hexdigest()
assert digest=="fa97c28572dafe133611a725ae7f731ee935481b2eb08891e00ed8ba82b7e3e6", ("CI69 payload integrity",digest)
with tempfile.TemporaryDirectory() as temp:
    f=Path(temp)/"ci69.patch"; f.write_bytes(patch)
    subprocess.run(["git","apply","--check","--whitespace=nowarn",str(f)],cwd=backend,check=True)
    subprocess.run(["git","apply","--whitespace=nowarn",str(f)],cwd=backend,check=True)
print("CI69 NGX-only manual source overlay applied; sha256:",digest)
