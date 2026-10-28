#include "ProducerContract.hpp"
#include <cassert>
#include <cstring>
#include <iostream>
#include <limits>

using namespace uevr::duoview::stereo::provenance;
static std::array<float,16> identity() {
    std::array<float,16> m{};m[0]=m[5]=m[10]=m[15]=1.0f;return m;
}
static Eye eye(Role role,uint64_t view) {
    Eye e{};e.matricesFromProducer=true;
    e.depthClipFromWorld=e.depthWorldFromClip=e.colorClipFromWorld=identity();
    Stamp x{};x.sceneFrame=100;x.viewGeneration=3;x.viewFamily=41;
    x.viewToken=view;x.stageFamily=91;x.projectionToken=view+1000;
    x.jitterToken=view+2000;x.originToken=777;
    x.resourceGeneration=view+10;x.producerWrite=1;x.producerFence=1;
    x.role=role;x.authenticated=x.owned=x.submitted=x.gpuReady=true;
    e.color=x;e.color.stage=Stage::SceneColor;
    e.depth=x;e.depth.stage=Stage::SceneDepth;
    e.depth.resourceGeneration=view+11;
    return e;
}
static Pair good() {
    Pair p{};p.left=eye(Role::LeftFovea,1);
    p.right=eye(Role::RightPeriphery,2);
    p.consumedSceneFrame=100;p.consumedViewGeneration=3;
    return p;
}
static void check(Reject actual,Reject expected) {
    if(actual!=expected){
        std::cerr<<"Expected "<<name(expected)<<" got "<<name(actual)<<"\n";
        std::abort();
    }
}
int main() {
    Pair p{};check(verify(p),Reject::NoLeftDepth);
    p=good();check(verify(p),Reject::None);
    p.left.depth.authenticated=false;check(verify(p),Reject::NoLeftDepth);
    p=good();p.right.depth.authenticated=false;check(verify(p),Reject::NoRightDepth);
    p=good();p.right.color.role=Role::LeftFovea;check(verify(p),Reject::RoleUnverified);
    p=good();p.right.depth.sceneFrame=101;check(verify(p),Reject::SourceFrameMismatch);
    p=good();p.right.color.sceneFrame=101;p.right.depth.sceneFrame=101;
    check(verify(p),Reject::SourceFrameMismatch);
    p=good();p.right.depth.stageFamily=99;check(verify(p),Reject::SourceStageMismatch);
    p=good();p.left.depth.projectionToken=0;check(verify(p),Reject::SourceViewMismatch);
    p=good();p.left.depth.jitterToken=0;check(verify(p),Reject::SourceViewMismatch);
    p=good();p.right.depth.originToken=700;check(verify(p),Reject::WorldOriginMismatch);
    p=good();p.left.matricesFromProducer=false;check(verify(p),Reject::DepthMatrixUnknown);
    p=good();p.left.depthClipFromWorld[2]=std::numeric_limits<float>::quiet_NaN();
    check(verify(p),Reject::InvalidMatrix);
    p=good();p.right.color.retired=true;check(verify(p),Reject::SlotRetired);
    p=good();p.left.color.owned=false;check(verify(p),Reject::ResourceUnowned);
    p=good();p.right.depth.gpuReady=false;check(verify(p),Reject::GPUWaitFail);
    p=good();p.consumedSceneFrame=101;check(verify(p),Reject::SourceFrameMismatch);
    p=good();p.consumedViewGeneration=2;check(verify(p),Reject::SourceFrameMismatch);
    p=good();p.right.color.viewToken=1;p.right.depth.viewToken=1;
    p.right.color.projectionToken=p.right.depth.projectionToken=1001;
    p.right.color.jitterToken=p.right.depth.jitterToken=2001;
    check(verify(p),Reject::RoleUnverified);
    std::cout<<"PASS CI31 typed scene producer provenance fail-closed contract\n";
    return 0;
}
