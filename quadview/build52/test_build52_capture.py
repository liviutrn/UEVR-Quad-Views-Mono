import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=ROOT/"QuadViewD3D12.hpp"
PATCH=Path(__file__).with_name("apply_auto_capture.py")
CAPTURE=Path(__file__).with_name("QuadViewAutoCapture.hpp")
TRACE=Path(__file__).with_name("QuadViewAutoTrace.hpp")

spec=importlib.util.spec_from_file_location("build52_patch",PATCH)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Build52SourceContract(unittest.TestCase):
    def test_guarded_integration(self):
        before=ORIGINAL.read_text(encoding="utf-8")
        after=module.patch_header(before)
        self.assertIn('build52_capture_.queue(commands,device_.Get(),sources,layout,',after)
        self.assertIn('source_generation,source_serial,source_engine_frame);',after)
        self.assertIn('uint64_t source_generation = 0,uint64_t source_serial = 0,',after)
        self.assertIn("build52_capture_.finish();",after)
        self.assertEqual(after.count('build52_capture_.queue('),1)
        self.assertEqual(after.count('build52_capture_.finish('),1)
        self.assertEqual(after.count('commands->DrawInstanced(3, 1, 0, 0);'),1)
        self.assertEqual(after.count('barrier(commands, destination, D3D12_RESOURCE_STATE_RENDER_TARGET, destination_state);'),1)
        self.assertNotIn('build52_capture_',before)
        with self.assertRaises(RuntimeError):
            module.patch_header(after)
    def test_header_maintains_separate_gpu_stage_and_fence(self):
        code=CAPTURE.read_text(encoding="utf-8")
        self.assertIn("D3D12_RESOURCE_STATE_COPY_SOURCE",code)
        self.assertIn("CopyTextureRegion(",code)
        self.assertIn("D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE",code)
        self.assertIn("write_store_zip",code)
        self.assertIn("coverage_tiles_64px.csv",code)
        self.assertIn("GetCurrentProcessId()",code)
        self.assertIn("GetCopyableFootprints(",code)
        self.assertIn('"hook_trace.csv"',code)
        self.assertIn('"source_generation="',code)
        self.assertIn('persist_hook_event(141,r,1);',code)
    def test_consumer_capture_correlation(self):
        before=(ROOT/"apply_quadview_consumer.py").read_text(encoding="utf-8")
        after=module.patch_consumer(before)
        self.assertIn('source->generation,source->serial,source->engine_frame);',after)
        with self.assertRaises(RuntimeError):
            module.patch_consumer(after)
    def test_hook_trace_runs_before_compositor(self):
        runtime=(ROOT/"hook_trace_runtime.inc").read_text(encoding="utf-8")
        demand='''    if (vr->is_quadview_mode_selected()) {
        const auto demanded=vr->quadview_desired_view_count();'''
        after=module.patch_hook_trace(runtime+"\n"+demand)
        self.assertIn('diagnostics::persist_hook_event(site,r,decision.count);',after)
        self.assertIn('r.event="VIEW_DEMAND"',after)
        self.assertIn('uevr::quadview::emit_hook_trace(142,r);',after)
        self.assertIn('#include "QuadViewAutoTrace.hpp"',after)
        with self.assertRaises(RuntimeError):
            module.patch_hook_trace(after)
    def test_trace_is_crash_survivable_and_bounded(self):
        code=TRACE.read_text(encoding="utf-8")
        self.assertIn('UEVR_Build52_Trace_',code)
        self.assertIn('std::fclose(f);',code)
        self.assertIn('if (written>=1600)',code)
        self.assertIn('std::try_to_lock',code)
    def test_no_original_files_modified_by_patch_function(self):
        before=ORIGINAL.read_text(encoding="utf-8")
        module.patch_header(before)
        self.assertEqual(ORIGINAL.read_text(encoding="utf-8"),before)

if __name__=="__main__":
    unittest.main()
