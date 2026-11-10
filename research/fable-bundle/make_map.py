import re, subprocess
from pathlib import Path
be=Path('/home/claude/rep/backend'); out=Path('/home/claude/fable')
L=['# Part E - Code map (B42.1 generated tree): where things are\n',
 'Line numbers = generated tree. Files marked ADDED are full in Part D; changed upstream files are diffs in Part C.\n']
added=sorted(subprocess.run(['git','ls-files','--others','--exclude-standard','src'],cwd=be,capture_output=True,text=True).stdout.split())
fn=re.compile(r'^\s*(?:template<[^>]*>\s*)?(?:inline\s+|static\s+|constexpr\s+|virtual\s+)*[\w:<>,\*&\s]+?\b(\w+)\s*\([^;{]*\)\s*(?:const\s*)?(?:noexcept\s*)?\{')
cls=re.compile(r'^\s*(?:struct|class)\s+(\w+)[^;]*\{')
for a in added:
    t=(be/a).read_text(errors='replace').split('\n')
    head=' '.join(l.strip('/ ').strip() for l in t[:12] if l.strip().startswith('//'))[:400]
    L.append(f'\n## ADDED {a} ({len(t)} lines)\n{head}')
    items=[]
    for i,l in enumerate(t,1):
        m=cls.match(l)
        if m: items.append(f'{m.group(1)}@{i}'); continue
        m=fn.match(l)
        if m and m.group(1) not in ('if','for','while','switch','return','catch'): items.append(f'{m.group(1)}()@{i}')
    if items: L.append('Symbols: '+', '.join(items[:80])+(' ...' if len(items)>80 else ''))
# changed files: list hunks with nearest enclosing function
diff=subprocess.run(['git','diff','-U0','5ac7edc','--','src'],cwd=be,capture_output=True,text=True,errors='replace').stdout
cur=None
for line in diff.split('\n'):
    if line.startswith('+++ b/'):
        cur=line[6:]; L.append(f'\n## CHANGED {cur}')
    elif line.startswith('@@') and cur:
        m=re.match(r'@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@ ?(.*)',line)
        if m and int(m.group(2) or 1)>=3:
            L.append(f'- +{m.group(1)} ({m.group(2) or 1} lines) in: {m.group(3)[:120]}')
(out/'fable-E-code-map.md').write_text('\n'.join(L)+'\n')
