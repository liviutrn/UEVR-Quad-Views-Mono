#include "QuadViewFamilyRouting.hpp"

#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <span>
#include <stdexcept>

using namespace uevr::quadview;

static FamilyIdentity family(uintptr_t id,uintptr_t scene,uintptr_t target,
                             std::array<uintptr_t,4> views) {
    FamilyIdentity value{};
    value.family=id; value.scene=scene; value.target=target;
    std::copy(views.begin(),views.end(),value.views.begin());
    value.view_count=4; value.readable=true;
    return value;
}

struct MutableFamily {
    std::array<int,4> views{11,12,13,14};
    int count{4};
    int target{100};
};

int main() {
    const FrozenFamilyIdentity expected{0x100,0x200,0x300,{0x401,0x402,0x403,0x404}};
    const auto main=family(expected.family,expected.scene,expected.target,expected.views);
    const auto auxiliary=family(0x110,0x220,0x330,{0x441,0x442,0x443,0x444});
    const auto other=family(0x120,0x230,0x340,{0x451,0x452,0x453,0x454});

    std::array<FamilyIdentity,3> batch{auxiliary,main,other};
    for (size_t main_index=0;main_index<batch.size();++main_index) {
        batch={auxiliary,main,other};
        if (main_index==0) batch={main,auxiliary,other};
        else if (main_index==2) batch={auxiliary,other,main};
        const auto route=route_main_family(batch,expected);
        assert(route.status==FamilyRouteStatus::main_family);
        assert(route.index==main_index);
        assert(batch[route.index].family==expected.family);
    }

    const std::array<FamilyIdentity,2> auxiliary_only{auxiliary,other};
    assert(route_main_family(auxiliary_only,expected).status==FamilyRouteStatus::auxiliary_only);
    auto opaque_auxiliary=auxiliary;
    opaque_auxiliary.scene=0; opaque_auxiliary.target=0; opaque_auxiliary.views={};
    opaque_auxiliary.view_count=0;
    const std::array<FamilyIdentity,1> null_scene_auxiliary{opaque_auxiliary};
    assert(route_main_family(null_scene_auxiliary,expected).status==FamilyRouteStatus::auxiliary_only);
    const std::array<FamilyIdentity,2> null_scene_batch{opaque_auxiliary,main};
    assert(route_main_family(null_scene_batch,expected).status==FamilyRouteStatus::main_family);
    assert(route_main_family(null_scene_batch,expected).index==1);
    const PartialFamilyIdentity partial{0,expected.scene,expected.target,{expected.views[0]},1};
    assert(classify_partial_main_family(null_scene_auxiliary,partial)==PartialFamilyRouteStatus::auxiliary_only);
    assert(classify_partial_main_family(null_scene_batch,partial)==PartialFamilyRouteStatus::possible_main);
    const std::array<FamilyIdentity,1> actual_primary{main};
    assert(classify_partial_main_family(actual_primary,PartialFamilyIdentity{0,0,expected.target,{},{}})==
        PartialFamilyRouteStatus::possible_main);
    assert(classify_partial_main_family(actual_primary,PartialFamilyIdentity{})==
        PartialFamilyRouteStatus::possible_main);

    const std::array<FamilyIdentity,2> duplicate_main{main,main};
    assert(route_main_family(duplicate_main,expected).status==FamilyRouteStatus::ambiguous_main);

    auto wrong_target=main; wrong_target.target=0x999;
    const std::array<FamilyIdentity,1> damaged_target{wrong_target};
    assert(route_main_family(damaged_target,expected).status==FamilyRouteStatus::malformed_main);

    auto reordered=main;
    std::swap(reordered.views[0],reordered.views[1]);
    const std::array<FamilyIdentity,1> damaged_order{reordered};
    assert(route_main_family(damaged_order,expected).status==FamilyRouteStatus::malformed_main);

    auto copied_main=main; copied_main.family=0x777;
    const std::array<FamilyIdentity,2> copied_batch{auxiliary,copied_main};
    assert(route_main_family(copied_batch,expected).status==FamilyRouteStatus::malformed_main);

    auto unreadable=other; unreadable.readable=false;
    const std::array<FamilyIdentity,2> unreadable_batch{main,unreadable};
    assert(route_main_family(unreadable_batch,expected).status==FamilyRouteStatus::malformed_batch);

    const std::array<int,4> main_views{11,12,13,14};
    const std::array<int,4> native_targets{201,202,203,204};
    MutableFamily mutable_family{};
    const auto original=mutable_family;
    int original_batch_calls{},singleton_calls{},auxiliary_draws{};
    bool source_registered{};
    const auto nested_callback=[&](size_t slot) {
        assert(mutable_family.count==1);
        assert(mutable_family.views[0]==main_views[slot]);
        assert(mutable_family.target==native_targets[slot]);
    };
    const auto dispatch=dispatch_main_views(
        mutable_family.views.data(),mutable_family.views.size(),mutable_family.count,mutable_family,
        main_views,native_targets,
        [](const MutableFamily& value) { return value.target; },
        [](MutableFamily& value,int target) { value.target=target; },
        [](size_t) { return true; },
        [&]() { ++original_batch_calls; ++auxiliary_draws; source_registered=true; nested_callback(0); },
        [&]() { ++singleton_calls; nested_callback(static_cast<size_t>(singleton_calls)); },
        [&](size_t slot) {
            return (slot!=0 || source_registered) && mutable_family.count==1 &&
                mutable_family.views[0]==main_views[slot] &&
                mutable_family.target==native_targets[slot];
        });
    assert(dispatch && dispatch.completed==4);
    assert(original_batch_calls==1 && singleton_calls==3 && auxiliary_draws==1);
    assert(mutable_family.views==original.views && mutable_family.count==original.count &&
        mutable_family.target==original.target);

    source_registered=false;
    int failed_first_batch_calls{},should_not_run_singletons{};
    const auto failed_first_registration=dispatch_main_views(
        mutable_family.views.data(),mutable_family.views.size(),mutable_family.count,mutable_family,
        main_views,native_targets,
        [](const MutableFamily& value) { return value.target; },
        [](MutableFamily& value,int target) { value.target=target; },
        [](size_t) { return true; },
        [&]() { ++failed_first_batch_calls; },
        [&]() { ++should_not_run_singletons; },
        [&](size_t slot) {
            return (slot!=0 || source_registered) && mutable_family.count==1 &&
                mutable_family.views[0]==main_views[slot] &&
                mutable_family.target==native_targets[slot];
        });
    assert(failed_first_registration.status==MainFamilyDispatchStatus::callback_validation_failed);
    assert(failed_first_registration.completed==0 && failed_first_batch_calls==1 &&
        should_not_run_singletons==0);
    assert(mutable_family.views==original.views && mutable_family.count==original.count &&
        mutable_family.target==original.target);

    auto early_failure=dispatch_main_views(
        mutable_family.views.data(),mutable_family.views.size(),mutable_family.count,mutable_family,
        main_views,native_targets,
        [](const MutableFamily& value) { return value.target; },
        [](MutableFamily& value,int target) { value.target=target; },
        [](size_t) { return true; },[]() {},[]() {},
        [](size_t slot) { return slot<2; });
    assert(early_failure.status==MainFamilyDispatchStatus::callback_validation_failed);
    assert(early_failure.completed==2);
    assert(mutable_family.views==original.views && mutable_family.count==original.count &&
        mutable_family.target==original.target);

    try {
        (void)dispatch_main_views(
            mutable_family.views.data(),mutable_family.views.size(),mutable_family.count,mutable_family,
            main_views,native_targets,
            [](const MutableFamily& value) { return value.target; },
            [](MutableFamily& value,int target) { value.target=target; },
            [](size_t) { return true; },[]() {},
            []() { throw std::runtime_error("nested renderer callback failed"); },
            [](size_t) { return true; });
        assert(false);
    } catch (const std::runtime_error&) {}
    assert(mutable_family.views==original.views && mutable_family.count==original.count &&
        mutable_family.target==original.target);

    std::cout << "Exact TArrayView main-family routing, auxiliary ordering, ambiguity, nested callback and restoration passed.\n";
}
