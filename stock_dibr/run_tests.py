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
    run(['cl','/nologo','/std:c++20','/EHsc','/W4','/WX',here/'candidate_policy_tests.cpp','/Fe:candidate-policy-tests.exe'])
    run([out/'candidate-policy-tests.exe'])
    run(['cl','/nologo','/std:c++20','/EHsc','/W4','/I'+str(root/'src'),'/I'+str(out),
         here/'gpu_test.cpp','/Fe:gpu-test.exe','/link','d3d12.lib','dxgi.lib','d3dcompiler.lib'])
    run([out/'gpu-test.exe'])
    run(['cl','/nologo','/std:c++20','/EHsc','/W4','/I'+str(root/'src'),'/I'+str(out),
         here/'hook_tests.cpp','/Fe:hook-tests.exe','/link','d3d12.lib','dxgi.lib'])
    run([out/'hook-tests.exe'])
    run(['cl','/nologo','/std:c++20','/EHsc','/W4','/I'+str(root/'src'),'/I'+str(out),
         here/'transaction_tests.cpp','/Fe:transaction-tests.exe','/link','d3d12.lib','dxgi.lib','d3dcompiler.lib'])
    run([out/'transaction-tests.exe'])
else:
    run(['g++','-std=c++20','-Wall','-Wextra','-Werror',here/'policy_tests.cpp','-o',out/'policy-tests'])
    run([out/'policy-tests'])
    run(['g++','-std=c++20','-Wall','-Wextra','-Werror',here/'candidate_policy_tests.cpp','-o',out/'candidate-policy-tests'])
    run([out/'candidate-policy-tests'])
    print('Windows WARP tests require Windows; not executed here.',flush=True)
(out/'test-scope.json').write_text(json.dumps({'production_shader':True,'production_capture_header':True,
    'candidate_policy_tests':True,
    'depth_candidate_selection_pixels_and_reset':sys.platform=='win32',
    'depth_inspector_binocular_pixel_oracles':sys.platform=='win32',
    'depth_filtering_repair_and_preserve2x_oracles':sys.platform=='win32',
    'queue_submit_hook_distinct_proxy_vtables':sys.platform=='win32','streamline_native_interface_discovery':sys.platform=='win32',
    'cross_queue_gpu_wait':sys.platform=='win32','wrong_producer_rejected':sys.platform=='win32',
    'com_list_aliases':sys.platform=='win32','nested_wrapper_native_callback':sys.platform=='win32','observer_reentrancy_guard':sys.platform=='win32','strength_changes_pixels':sys.platform=='win32',
    'viewport_producer_rectangle':sys.platform=='win32','strength_full_range_monotonic':sys.platform=='win32','late_binding_rejected':sys.platform=='win32','teardown_forwarding':sys.platform=='win32',
    'immediate_reset_after_submit':sys.platform=='win32','serialized_dsv_replay':sys.platform=='win32','queue_callback_order':sys.platform=='win32','detached_retirement':sys.platform=='win32','transaction_fault_injection':sys.platform=='win32','failed_depth_signals_retained_across_reset':sys.platform=='win32','manual_submit_callback':False,
    'windows_warp_executed':sys.platform=='win32','game_tested':False,'headset_tested':False},indent=2))
