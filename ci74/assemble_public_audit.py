"""Materialize public shader/guide audit subset; NOT a complete UEVR backend.

The actual production pipeline remains the existing pinned-SDK workflow.
Unavailable FFakeStereoRenderingHook.cpp and D3D12Component.hpp are skipped
only in this test-only materializer; all available patch anchors still run.
"""
from pathlib import Path
import base64
import gzip
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys

def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def main(workspace, backend):
    shutil.copytree(workspace/"ci51/production",backend,dirs_exist_ok=True)
    target=backend/"src/mods/vr"
    for source in (workspace/"duoview").glob("*"):
        if source.is_file() and not (target/source.name).exists():
            shutil.copyfile(source,target/source.name)
    bridge=load("bridge",workspace/"ci51/build67_bridge.py")
    original=bridge.replace_once
    def replace_available(path,a,b):
        if path.is_file():original(path,a,b)
        else:print("TEST SUBSET skips unavailable",path.name)
    bridge.replace_once=replace_available
    bridge.apply(backend)
    old=gzip.decompress(base64.b64decode((workspace/"ci69/payload.b64").read_text().strip()))
    assert hashlib.sha256(old).hexdigest()=="fa97c28572dafe133611a725ae7f731ee935481b2eb08891e00ed8ba82b7e3e6"
    delta=json.loads(gzip.decompress(base64.b64decode((workspace/"ci69/final_delta.b64").read_text().strip())))
    lines=old.decode().splitlines(keepends=True);parts=[];cursor=0
    for tag,start,end,replacement in delta:
        if tag not in ("replace","insert","delete") or not cursor<=start<=end<=len(lines):
            raise RuntimeError("CI69 patch delta bounds")
        parts.extend(lines[cursor:start]);parts.append(replacement);cursor=end
    parts.extend(lines[cursor:]);patch="".join(parts).encode()
    assert hashlib.sha256(patch).hexdigest()=="e7aba90d7b9aebab355810b51be8894bce05fa084da8fc612f5c3f340109ad40"
    subprocess.run(["git","init","-q",str(backend)],check=True)
    includes=["--include="+p.relative_to(backend).as_posix() for p in (backend/"src").rglob("*") if p.is_file()]
    for check in (True,False):
        subprocess.run(["git","apply",*(["--check"] if check else []),*includes,"-"],
                       input=patch,cwd=backend,check=True)
    ci70=load("ci70",workspace/"ci70/apply.py");original70=ci70.replace
    def replace70(path,a,b):
        if path.is_file():original70(path,a,b)
        else:print("TEST SUBSET skips unavailable",path.name)
    ci70.replace=replace70;ci70.apply(backend)
    load("ci71",workspace/"ci71/apply.py").run(backend)
    load("ci72",workspace/"ci72/apply.py").apply(backend)
    subprocess.run([sys.executable,str(workspace/"ci73/apply.py"),str(backend)],check=True)
    print("Public CI73 audit subset assembled; SDK backend NOT reconstructed")

if __name__=="__main__":
    main(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
