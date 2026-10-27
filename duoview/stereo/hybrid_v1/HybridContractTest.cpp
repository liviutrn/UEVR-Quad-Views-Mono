#include "HybridContract.hpp"
#include <cassert>
int main() {
    using namespace uevr::duoview::stereo;
    HybridConstants constants{};
    assert(sizeof(constants)==432);
    assert(offsetof(HybridConstants,flags)==416);
    StereoProvenance p{};
    assert(!p.canSynthesize());
    p.leftSceneColorDepthSamePass=true;
    p.rightSceneColorDepthSamePass=true;
    p.sourceFrameSynchronized=true;
    p.matricesCameraRelative=true;
    assert(!p.canSynthesize());
    p.outputsReady=true;
    assert(p.canSynthesize());
    return 0;
}
