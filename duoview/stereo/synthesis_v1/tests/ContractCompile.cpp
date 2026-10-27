#include "../StereoBackwardContract.hpp"
#include "../StereoMatrixRebase.hpp"
#include <cmath>
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
  gate.cameraRelativeOriginProven=true;
  gate.viewMatricesMatchDepth=true;
  gate.compatibleColorEncoding=true;
  assert(!gate.canDispatch());
  gate.renderTargetsReady=true;
  assert(gate.canDispatch());

  AbsoluteMatrices input{};
  // Two eyes are approximately 7.2 UU apart even when the UE world is far
  // from origin, where float cannot preserve single-centimeter geometry.
  const double x=100000000.0;
  input.targetWorldFromClip=Translate(x+3.6,0,0);
  input.sourceDepthClipFromWorld=Translate(-(x-3.6),0,0);
  input.sourceDepthWorldFromClip=Translate(x-3.6,0,0);
  input.sourceColorClipFromWorld=input.sourceDepthClipFromWorld;
  input.sourceCameraWorld={x-3.6,0,0};
  input.targetCameraWorld={x+3.6,0,0};
  BackwardConstants relative{};
  assert(ConfigureCameraRelative(relative,input,{x,0,0}));
  assert(std::abs(relative.sourceCameraWorld[0]+3.6f)<0.0001f);
  assert(std::abs(relative.targetCameraWorld[0]-3.6f)<0.0001f);
  assert(std::abs(relative.targetWorldFromClip[3]-3.6f)<0.0001f);
  assert(std::abs(relative.sourceDepthClipFromWorld[3]-3.6f)<0.0001f);
  assert(std::abs(relative.sourceDepthWorldFromClip[3]+3.6f)<0.0001f);
  return 0;
}
