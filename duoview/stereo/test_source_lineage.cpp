#include "SourceLineage.hpp"
#include <cassert>
#include <cstdio>
using namespace uevr::duoview::stereo;

static Pass valid(Role role) {
    Pass x{};
    x.generation=9; x.tick=48; x.serial=role==Role::Fovea?300:301;
    x.pose_token=99; x.projection_token=role==Role::Fovea?500:501;
    x.queue_token=808; x.gpu_copy_fence=12; x.gpu_queue_completed=12;
    x.color_stage_token=11; x.depth_stage_token=11;
    x.origin=Origin::Center; x.role=role;
    x.color_stage=Stage::SceneAfterUpscale; x.depth_stage=x.color_stage;
    x.proof=Proof::GeometryCalibrated; x.producer_pass_verified=true;
    x.matrices_calibrated=true;
    x.color={uintptr_t(100),5,1024,1024,0,80};
    x.depth={uintptr_t(101),6,1024,1024,0,46};
    return x;
}
int main() {
    const auto p=valid(Role::Periphery), f=valid(Role::Fovea);
    assert(ready_for_center_stereo(p,f));
    {auto q=f;q.tick++; assert(check_pair(p,q)==Reject::DifferentTick);}
    {auto q=f;q.pose_token++; assert(check_pair(p,q)==Reject::DifferentPose);}
    {auto q=f;q.origin=Origin::Left; assert(check_pair(p,q)==Reject::DifferentOrigin);}
    {auto q=f;q.role=Role::Periphery; assert(check_pair(p,q)==Reject::WrongRoles);}
    {auto q=f;q.producer_pass_verified=false;
        assert(check_pair(p,q)==Reject::UnmatchedColorDepth);}
    {auto q=f;q.depth_stage_token=29;
        assert(check_pair(p,q)==Reject::UnmatchedColorDepth);}
    {auto q=f;q.gpu_queue_completed=11;
        assert(check_pair(p,q)==Reject::UntrustedGPU);}
    {auto q=f;q.matrices_calibrated=false;
        assert(check_pair(p,q)==Reject::UncalibratedGeometry);}
    {auto q=f;q.projection_token=8888; assert(ready_for_center_stereo(p,q));}
    {auto q=f;q.color_stage=Stage::Unknown;
        assert(check_pair(p,q)==Reject::DifferentColorStage);}
    {auto q=f;q.generation++; assert(check_pair(p,q)==Reject::Generation);}
    {auto q=p;q.origin=Origin::Left; auto z=f;z.origin=Origin::Left;
        assert(check_pair(q,z)==Reject::None);
        assert(!ready_for_center_stereo(q,z));}
    std::puts("RGB-D lineage contract: 13 checks passed");
}
