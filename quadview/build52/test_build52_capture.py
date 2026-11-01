import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=ROOT/"QuadViewD3D12.hpp"
PATCH=Path(__file__).with_name("apply_auto_capture.py")
CAPTURE=Path(__file__).with_name("QuadViewAutoCapture.hpp")

spec=importlib.util.spec_from_file_location("build52_patch",PATCH)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Build52SourceContract(unittest.TestCase):
    def test_guarded_integration(self):
        before=ORIGINAL.read_text(encoding="utf-8")
        after=module.patch_header(before)
        self.assertIn('build52_capture_.queue(commands,device_.Get(),sources,layout);',after)
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
    def test_no_original_files_modified_by_patch_function(self):
        before=ORIGINAL.read_text(encoding="utf-8")
        module.patch_header(before)
        self.assertEqual(ORIGINAL.read_text(encoding="utf-8"),before)

if __name__=="__main__":
    unittest.main()
