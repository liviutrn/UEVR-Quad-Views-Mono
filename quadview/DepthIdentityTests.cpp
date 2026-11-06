#include "QuadViewDepthIdentity.hpp"
#include <stdexcept>
#include <thread>
#include <future>
using namespace uevr::quadview::ngx;
void check(bool ok) { if(!ok) throw std::runtime_error("Depth identity/lifetime contract"); }
int main() {
    // B19: capture and consumer must never see dimensions from different resizes.
    ExpectedPeripheryExtent expected;
    check(expected.load() == (std::array<uint32_t,2>{0u,0u}));
    expected.store(1920,1080);
    check(expected.load() == (std::array<uint32_t,2>{1920u,1080u}));
    std::atomic<bool> go{false}, done{false};
    bool torn_extent=false;
    std::thread resize_writer([&] {
        while (!go.load(std::memory_order_acquire)) std::this_thread::yield();
        for (int i=0;i<250000;++i)
            expected.store((i&1) ? 640u : 1536u, (i&1) ? 480u : 1024u);
        done.store(true, std::memory_order_release);
    });
    go.store(true, std::memory_order_release);
    while (!done.load(std::memory_order_acquire)) {
        const auto sample=expected.load();
        if (sample != (std::array<uint32_t,2>{1920u,1080u}) &&
            sample != (std::array<uint32_t,2>{640u,480u}) &&
            sample != (std::array<uint32_t,2>{1536u,1024u}))
            torn_extent=true;
    }
    resize_writer.join();
    check(!torn_extent);
    expected.store(0,0); check(expected.load()==(std::array<uint32_t,2>{0u,0u}));
    DepthOwner owner; owner.generation=2;owner.serial=7;owner.target_set=3;owner.engine_frame=4;
    owner.role=0;owner.output_width=400;owner.output_height=300;owner.unambiguous=true;owner.ngx_input_state_known=true;
    check(owner.valid());
    { DepthOwnerScope scope(owner);check(*DepthOwnerScope::current()==owner);
      auto ambiguous=owner;ambiguous.unambiguous=false;
      {DepthOwnerScope inner(ambiguous);check(!DepthOwnerScope::current());}
      check(*DepthOwnerScope::current()==owner);
      std::thread other([] {check(!DepthOwnerScope::current());});other.join(); }
    check(!DepthOwnerScope::current());
    auto stale=owner;stale.serial++;check(!(owner==stale));stale=owner;stale.target_set++;check(!(owner==stale));
    check(owner.matches(owner));
    stale=owner;stale.serial++;check(!owner.matches(stale));
    stale=owner;stale.target_set++;check(!owner.matches(stale));
    stale=owner;stale.engine_frame++;check(!owner.matches(stale));
    stale=owner;stale.projection[14]=1.;check(!owner.matches(stale));
    stale=owner;stale.role=2;check(!owner.matches(stale));
    DepthRecordingEpochs epochs;
    const auto epoch=epochs.current(0x1234);
    check(epochs.matches(0x1234,epoch));
    check(!epochs.matches(0x5678,epoch));
    epochs.reset(0x1234); // old recording discarded, same object reused
    check(!epochs.matches(0x1234,epoch));
    check(epochs.matches(0x1234,epoch+1));
    using Clock=std::chrono::steady_clock;
    const auto born=Clock::time_point(std::chrono::seconds(1));
    check(depth_capture_in_window(born,born,born+std::chrono::milliseconds(20)));
    check(!depth_capture_in_window(born-std::chrono::milliseconds(1),born,born+std::chrono::milliseconds(20)));
    check(!depth_capture_in_window(born,born,born+std::chrono::milliseconds(250)));
    check(!depth_capture_in_window(born+std::chrono::milliseconds(21),born,born+std::chrono::milliseconds(20)));
    check(!depth_capture_in_window(born,{},born));
    const auto discarded_epoch=epochs.current(0x7777);
    epochs.prune([](uintptr_t list){return list!=0x7777;});
    const auto reused_address=epochs.current(0x7777);
    check(reused_address!=discarded_epoch);
    check(!epochs.matches(0x7777,discarded_epoch));
    for(uintptr_t list=0x10000;list<0x10400;++list) {
        epochs.prune([&](uintptr_t old){return old==list;});
        check(epochs.current(list)!=0); // long address churn never saturates
    }
    check(epochs.reset(0x9999)==0); // Reset of an unrelated list allocates no identity
    DepthSubmissionSequence submission;
    bool submitted=false;
    std::promise<void> attempted;auto attempted_future=attempted.get_future();
    auto executing=submission.acquire();
    std::thread resetting([&] {
        auto early=submission.try_acquire();
        check(!early.owns_lock()); // driver Execute returned, bookkeeping still owns interval
        attempted.set_value();
        auto after=submission.acquire();
        check(submitted); // Reset cannot classify that enqueued recording as discarded
    });
    attempted_future.wait();submitted=true;executing.unlock();resetting.join();
    { auto first=submission.acquire();auto nested=submission.acquire(); } // wrapped driver reentry
    check(!depth_slot_reusable(true,false,100,0,1)); // even after arbitrary time
    check(!depth_slot_reusable(false,true,9,10,1));
    check(!depth_slot_reusable(false,true,~uint64_t{},10,1));
    check(!depth_slot_reusable(false,true,10,10,2)); // compositor lease
    check(depth_slot_reusable(false,true,10,10,1));
}
