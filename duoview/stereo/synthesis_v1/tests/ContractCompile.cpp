#include "../StereoBackwardContract.hpp"
#include <cassert>
int main() {
  using namespace uevr::duoview::stereo;
  BackwardConstants cb{};
  assert(sizeof(cb)==416);
  assert(offsetof(BackwardConstants,outputConfig)==400);
  BindingContract gate{};
  assert(!gate.canDispatch());
  gate.depthEyeProven=true;
  gate.frameGenerationMatches=true;
  gate.viewMatricesMatchDepth=true;
  gate.compatibleColorEncoding=true;
  assert(!gate.canDispatch());
  gate.renderTargetsReady=true;
  assert(gate.canDispatch());
  return 0;
}
