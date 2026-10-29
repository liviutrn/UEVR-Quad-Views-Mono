from pathlib import Path
import subprocess,sys,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'duoview'))
from embed_shader import fxc_executable,format_array
source=Path(sys.argv[1]).resolve()/'src/mods/vr'
sections=[]
entries=[('VSMain','vs_5_0','vertex_shader_bytecode','DuoViewCompositeRaster.hlsl'),
 ('PSMain','ps_5_0','pixel_shader_bytecode','DuoViewCompositeRaster.hlsl'),
 ('PSNativeMain','ps_5_0','native_pixel_shader_bytecode','DuoViewNativeCompositeRaster.hlsl'),
 ('PSNativeStereo','ps_5_0','native_stereo_shader_bytecode','DuoViewStereoCompositeRaster.hlsl'),
 ('PSDepthDiagnostic','ps_5_0','native_depth_debug_shader_bytecode','DuoViewDepthDiagnosticRaster.hlsl'),
 ('VSSurface','vs_5_0','surface_vertex_shader_bytecode','DuoViewSurfaceReproject.hlsl'),
 ('PSSurface','ps_5_0','surface_pixel_shader_bytecode','DuoViewSurfaceReproject.hlsl'),
 ('PSBackwardSurface','ps_5_0','backward_pixel_shader_bytecode','DuoViewSurfaceReproject.hlsl')]
with tempfile.TemporaryDirectory(prefix='duoview-ci51-shaders-') as tmp:
 for entry,profile,name,file in entries:
    output=Path(tmp)/(name+'.cso')
    subprocess.run([str(fxc_executable()),'/nologo','/O3','/T',profile,'/E',entry,'/I',str(source),'/Fo',str(output),str(source/file)],check=True)
    sections.append(format_array(name,output.read_bytes()))
(source/'DuoViewShaderSource.hpp').write_text('#pragma once\n// Compiled from final CI51 production HLSL.\nnamespace uevr::duoview::dx12 {\n'+''.join(sections)+'}\n',encoding='utf-8',newline='')
print('PASS: all eight final live shader entries compiled offline with FXC')
