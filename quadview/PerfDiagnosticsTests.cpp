#include "QuadViewPerfDiagnostics.hpp"
#include <cassert>
int main() {
  using namespace uevr::quadview::perf;
  reset();
  assert(begin()==Time{});
  set_enabled(true);
  auto started=begin();
  end_role(0,started); end_role(2,started); end_role(3,started);
  assert(source_context_cpu.snapshot().count==1);
  assert(source_left_cpu.snapshot().count==1);
  assert(source_right_cpu.snapshot().count==1);
  retired_gpu(2.2f,0.3f);
  assert(composite_gpu.snapshot().count==1);
  assert(seam_analysis_gpu.snapshot().count==1);
  output_accepted(); output_accepted(); output_failed(); source_missing();
  assert(composed.load()==2 && copy_failed.load()==1 && missing_source.load()==1);
  set_enabled(false);
  assert(begin()==Time{});
  reset();
  assert(composite_gpu.snapshot().count==0);
  return 0;
}
