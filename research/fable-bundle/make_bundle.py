import subprocess, re, sys
from pathlib import Path
repo=Path('/home/claude/repo'); be=Path('/home/claude/rep/backend'); out=Path('/home/claude/fable')
wf=(repo/'.github/workflows/triview-b1.yml').read_text()
steps=[]; seen=set()
for m in re.finditer(r'python workspace/(quadview/[A-Za-z0-9_/]+\.py)', wf):
    p=m.group(1)
    if p in seen: continue
    seen.add(p); steps.append(p)
# Part B: patch chain
lines=['# Part B - Patch chain (exact order in .github/workflows/triview-b1.yml, B42.1)\n',
 'Each script edits the pinned upstream tree (Joey UEVR 5ac7edc + private UESDK 3cffbc8 + frontend 60be4b0). '
 'test_*/verify_* steps are checks, not edits. Summary = first lines of each script docstring.\n']
for i,p in enumerate(steps,1):
    f=repo/'workspace'/p if (repo/'workspace'/p).exists() else repo/p
    doc=''
    try:
        t=f.read_text(encoding='utf-8',errors='replace')
        m=re.search(r'"""(.*?)"""',t,re.S)
        if m: doc=' '.join(m.group(1).strip().split('\n')[:6])
        elif t.startswith('#!'): doc=' '.join(l.lstrip('# ') for l in t.split('\n')[1:5] if l.startswith('#'))
    except Exception as e: doc=f'(unreadable: {e})'
    kind='CHECK' if re.search(r'(^|/)(test_|verify_)|Tests',p) else 'EDIT'
    lines.append(f'{i}. [{kind}] `{p}` ({f.stat().st_size//1024 if f.exists() else 0} KB) - {doc[:600]}')
(out/'fable-B-patch-chain.md').write_text('\n'.join(lines)+'\n')
# Part C: generated diff (tracked upstream files)
diff=subprocess.run(['git','diff','-U6','5ac7edc','--','src'],cwd=be,capture_output=True,text=True,errors='replace').stdout
hdr='# Part C - Generated changes to upstream Joey UEVR files (B42.1 tree vs 5ac7edc), unified diff -U6\nLine numbers in @@ headers are the generated-tree line numbers (+side). Private UESDK code is not included.\n\n'
chunks=re.split(r'(?=^diff --git )',diff,flags=re.M)
# Part D: added files
added=subprocess.run(['git','ls-files','--others','--exclude-standard','src'],cwd=be,capture_output=True,text=True).stdout.split()
dtext=['# Part D - Files ADDED to the tree by the patch chain (full source, B42.1 generated tree)\n']
for a in sorted(added):
    t=(be/a).read_text(encoding='utf-8',errors='replace')
    dtext.append(f'\n\n## FILE {a} ({t.count(chr(10))} lines)\n```cpp\n{t}\n```')
shaders=[p for p in sorted((repo/'quadview').glob('*.hlsl'))]
for s in shaders:
    t=s.read_text(encoding='utf-8',errors='replace')
    dtext.append(f'\n\n## SHADER quadview/{s.name} ({t.count(chr(10))} lines)\n```hlsl\n{t}\n```')
# write in <=950 KB parts
def write_parts(name,header,pieces):
    parts=[];cur=header
    for p in pieces:
        if len((cur+p).encode())>950_000 and cur!=header: parts.append(cur);cur=header
        cur+=p
    parts.append(cur)
    for i,c in enumerate(parts,1):
        (out/f'{name}-{i}.md').write_text(c)
    return len(parts)
nc=write_parts('fable-C-generated-diff',hdr,chunks)
nd=write_parts('fable-D-added-source',dtext[0],dtext[1:])
print('steps',len(steps),'C parts',nc,'D parts',nd)
