import pathlib, subprocess, sys, re, json
root=pathlib.Path(sys.argv[1]).resolve(); out=pathlib.Path(sys.argv[2]).resolve(); out.mkdir(parents=True,exist_ok=True)
here=pathlib.Path(__file__).resolve().parent
def run(args):
    print('RUN', ' '.join(map(str,args)), flush=True)
    subprocess.run(list(map(str,args)),check=True,cwd=out)
source=(root/'src/mods/vr/d3d12/DIBRPreview.cpp').read_text()
shader=''.join(re.findall(r'R"DIBR\((.*?)\)DIBR"',source,re.S))
assert shader and shader.count('float ReadDepth(')==1
(out/'production_shader.hpp').write_text('const char* shader =\n'+
    '\n'.join(json.dumps(shader[i:i+8000]) for i in range(0,len(shader),8000))+';\n')
header=(root/'src/mods/vr/d3d12/DIBRPreview.hpp').read_text()
constants=re.search(r'    struct alignas\(256\) Constants \{.*?\n    \};',header,re.S).group().replace('Constants','TestConstants')
(out/'production_constants.hpp').write_text(constants+'\nstatic_assert(sizeof(TestConstants)==256);\n')
if sys.platform=='win32':
    if not (root/'src/hooks/QueueSubmitHook.hpp').is_file():
        raise RuntimeError('QueueSubmitHook.hpp is missing; apply stock_dibr/apply_queue_fix.py before running the Windows GPU test.')
    run(['cl','/nologo','/std:c++20','/EHsc','/W4','/WX',here/'policy_tests.cpp','/Fe:policy-tests.exe'])
    run([out/'policy-tests.exe'])
    run(['cl','/nologo','/std:c++20','/EHsc','/W4','/I'+str(root/'src'),'/I'+str(out),
         here/'gpu_test.cpp','/Fe:gpu-test.exe','/link','d3d12.lib','dxgi.lib','d3dcompiler.lib'])
    run([out/'gpu-test.exe'])
else:
    run(['g++','-std=c++20','-Wall','-Wextra','-Werror',here/'policy_tests.cpp','-o',out/'policy-tests'])
    run([out/'policy-tests'])
    print('Windows WARP tests require Windows; not executed here.',flush=True)
(out/'test-scope.json').write_text(json.dumps({'production_shader':True,'production_capture_header':True,
    'queue_submit_hook_distinct_vtables':sys.platform=='win32','foreign_queue_rejection':sys.platform=='win32',
    'immediate_reset_after_submit':sys.platform=='win32','manual_submit_callback':False,
    'windows_warp_executed':sys.platform=='win32','game_tested':False,'headset_tested':False},indent=2))
