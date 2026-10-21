#pragma once

#include <array>
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <span>
#include <type_traits>

namespace uevr::quadview {

struct FamilyIdentity {
    uintptr_t family{}, scene{}, target{};
    std::array<uintptr_t,16> views{};
    uint8_t view_count{};
    bool readable{};
};

struct FrozenFamilyIdentity {
    uintptr_t family{}, scene{}, target{};
    std::array<uintptr_t,4> views{};
};

enum class FamilyRouteStatus : uint8_t {
    main_family,
    auxiliary_only,
    malformed_batch,
    malformed_main,
    ambiguous_main,
};

struct FamilyRoute {
    FamilyRouteStatus status{FamilyRouteStatus::malformed_batch};
    size_t index{};
    explicit operator bool() const { return status == FamilyRouteStatus::main_family; }
};

struct PartialFamilyIdentity {
    uintptr_t family{}, scene{}, target{};
    std::array<uintptr_t,16> views{};
    uint8_t view_count{};
};

enum class PartialFamilyRouteStatus : uint8_t { auxiliary_only, possible_main, malformed_batch };

inline bool valid_frozen_identity(const FrozenFamilyIdentity& expected) {
    if (!expected.family || !expected.scene || !expected.target) return false;
    for (size_t i=0;i<expected.views.size();++i) {
        if (!expected.views[i]) return false;
        for (size_t j=0;j<i;++j) if (expected.views[j] == expected.views[i]) return false;
    }
    return true;
}

inline bool same_frozen_view_order(const FamilyIdentity& candidate,
                                   const FrozenFamilyIdentity& expected) {
    if (candidate.view_count != expected.views.size()) return false;
    for (size_t i=0;i<expected.views.size();++i)
        if (candidate.views[i] != expected.views[i]) return false;
    return true;
}

inline bool same_frozen_view_set(const FamilyIdentity& candidate,
                                 const FrozenFamilyIdentity& expected) {
    if (candidate.view_count != expected.views.size()) return false;
    std::array<bool,4> matched{};
    for (size_t i=0;i<expected.views.size();++i) {
        bool found{};
        for (size_t j=0;j<expected.views.size();++j) {
            if (!matched[j] && candidate.views[i] == expected.views[j]) {
                matched[j]=true; found=true; break;
            }
        }
        if (!found) return false;
    }
    return true;
}

inline bool shares_frozen_view(const FamilyIdentity& candidate,
                               const FrozenFamilyIdentity& expected) {
    const auto count = candidate.view_count < candidate.views.size()
        ? candidate.view_count : candidate.views.size();
    for (size_t i=0;i<count;++i)
        for (const auto view : expected.views)
            if (view && candidate.views[i] == view) return true;
    return false;
}

inline PartialFamilyRouteStatus classify_partial_main_family(
    std::span<const FamilyIdentity> candidates,const PartialFamilyIdentity& partial) {
    if (candidates.empty() || partial.view_count > partial.views.size())
        return PartialFamilyRouteStatus::malformed_batch;
    bool possible_main{};
    for (const auto& candidate:candidates) {
        if (!candidate.readable || !candidate.family || candidate.view_count > candidate.views.size())
            return PartialFamilyRouteStatus::malformed_batch;
        if (partial.family && candidate.family == partial.family) possible_main=true;
        if (partial.target && candidate.target == partial.target &&
            (!partial.scene || candidate.scene == partial.scene)) possible_main=true;
        if (partial.scene && !partial.target && candidate.scene == partial.scene) possible_main=true;
        if (!partial.family && !partial.scene && !partial.target && !partial.view_count &&
            candidate.view_count == 4) possible_main=true;
        const auto count = candidate.view_count < candidate.views.size()
            ? candidate.view_count : candidate.views.size();
        for (size_t i=0;i<count;++i)
            for (size_t j=0;j<partial.view_count;++j)
                if (candidate.views[i] && candidate.views[i] == partial.views[j]) possible_main=true;
    }
    return possible_main ? PartialFamilyRouteStatus::possible_main :
        PartialFamilyRouteStatus::auxiliary_only;
}

inline FamilyRoute route_current_main_family(std::span<const FamilyIdentity> candidates,
                                             const FamilyIdentity& expected) {
    if (candidates.empty() || !expected.readable || !expected.family || !expected.scene ||
        !expected.target || expected.view_count == 0 || expected.view_count > expected.views.size())
        return {FamilyRouteStatus::malformed_batch,0};
    for (size_t i=0;i<expected.view_count;++i) {
        if (!expected.views[i]) return {FamilyRouteStatus::malformed_main,0};
        for (size_t j=0;j<i;++j) if (expected.views[j] == expected.views[i])
            return {FamilyRouteStatus::malformed_main,0};
    }
    size_t selected{};
    size_t exact_count{};
    bool suspect_main{};
    for (size_t i=0;i<candidates.size();++i) {
        const auto& candidate=candidates[i];
        if (!candidate.readable || !candidate.family || candidate.view_count > candidate.views.size())
            return {FamilyRouteStatus::malformed_batch,i};
        const bool same_views = candidate.view_count == expected.view_count &&
            std::equal(expected.views.begin(),expected.views.begin()+expected.view_count,candidate.views.begin());
        if (candidate.family == expected.family) {
            if (candidate.scene != expected.scene || candidate.target != expected.target || !same_views)
                return {FamilyRouteStatus::malformed_main,i};
            selected=i;
            ++exact_count;
            continue;
        }
        bool shares{};
        const auto count = candidate.view_count < candidate.views.size()
            ? candidate.view_count : candidate.views.size();
        for (size_t a=0;a<count;++a)
            for (size_t b=0;b<expected.view_count;++b)
                if (candidate.views[a] == expected.views[b]) shares=true;
        if (shares || (candidate.scene == expected.scene && candidate.target == expected.target))
            suspect_main=true;
    }
    if (exact_count > 1 || (exact_count != 0 && suspect_main))
        return {FamilyRouteStatus::ambiguous_main,selected};
    if (suspect_main) return {FamilyRouteStatus::malformed_main,0};
    if (exact_count == 1) return {FamilyRouteStatus::main_family,selected};
    return {FamilyRouteStatus::auxiliary_only,0};
}

// Selects only the unique family authenticated by the frozen construction
// snapshot. Other valid families are auxiliaries and remain in the caller's
// original batch. A candidate that looks like a copied or damaged main family
// fails closed instead of falling through to a legacy view-count heuristic.
inline FamilyRoute route_main_family(std::span<const FamilyIdentity> candidates,
                                     const FrozenFamilyIdentity& expected) {
    if (candidates.empty() || !valid_frozen_identity(expected))
        return {FamilyRouteStatus::malformed_batch,0};
    FamilyIdentity identity{};
    identity.family=expected.family; identity.scene=expected.scene; identity.target=expected.target;
    identity.view_count=4; identity.readable=true;
    std::copy(expected.views.begin(),expected.views.end(),identity.views.begin());
    return route_current_main_family(candidates,identity);
}

// Temporarily presents one frozen main view/target to the engine while keeping
// the outer auxiliary batch intact. The owner uses this once around all four
// callbacks; nested callbacks observe the selected singleton and cannot steal
// restoration ownership.
template<class View, class Target, class Context, class Getter, class Setter>
class ScopedMainFamilyMutation {
public:
    ScopedMainFamilyMutation(View* data, size_t capacity, int32_t& count, Context& context,
                             Getter getter, Setter setter)
        : data_{data}, capacity_{capacity}, count_{&count}, context_{&context},
          getter_{getter}, setter_{setter}, original_count_{count} {
        if (!data_ || capacity_ < original_.size() || original_count_ != static_cast<int32_t>(original_.size()))
            return;
        for (size_t i=0;i<original_.size();++i) original_[i]=data_[i];
        original_target_=getter_(*context_);
        valid_=true;
    }
    ScopedMainFamilyMutation(const ScopedMainFamilyMutation&)=delete;
    ScopedMainFamilyMutation& operator=(const ScopedMainFamilyMutation&)=delete;
    ~ScopedMainFamilyMutation() { restore(); }

    explicit operator bool() const { return valid_; }

    bool select_single(View view, Target target) {
        if (!valid_ || !view || !target) return false;
        data_[0]=view;
        *count_=1;
        setter_(*context_,target);
        return getter_(*context_) == target;
    }

    void restore() {
        if (!valid_) return;
        for (size_t i=0;i<original_.size();++i) data_[i]=original_[i];
        *count_=original_count_;
        setter_(*context_,original_target_);
        valid_=false;
    }

private:
    View* data_{};
    size_t capacity_{};
    int32_t* count_{};
    Context* context_{};
    Getter getter_;
    Setter setter_;
    std::array<View,4> original_{};
    Target original_target_{};
    int32_t original_count_{};
    bool valid_{};
};

enum class MainFamilyDispatchStatus : uint8_t {
    complete,
    invalid_storage,
    preparation_failed,
    selection_failed,
    callback_validation_failed,
};

struct MainFamilyDispatchResult {
    MainFamilyDispatchStatus status{MainFamilyDispatchStatus::invalid_storage};
    uint8_t completed{};
    explicit operator bool() const { return status == MainFamilyDispatchStatus::complete; }
};

template<class View, class Target, class Context, class Getter, class Setter,
         class Before, class FirstBatch, class Singleton, class Validate>
MainFamilyDispatchResult dispatch_main_views(
    View* data, size_t capacity, int32_t& count, Context& context,
    const std::array<View,4>& views, const std::array<Target,4>& targets,
    Getter getter, Setter setter, Before before, FirstBatch first_batch,
    Singleton singleton, Validate validate) {
    ScopedMainFamilyMutation<View,Target,Context,Getter,Setter> mutation{
        data,capacity,count,context,getter,setter};
    if (!mutation) return {MainFamilyDispatchStatus::invalid_storage,0};
    uint8_t completed{};
    for (size_t slot=0;slot<views.size();++slot) {
        if (!before(slot)) return {MainFamilyDispatchStatus::preparation_failed,completed};
        if (!mutation.select_single(views[slot],targets[slot]))
            return {MainFamilyDispatchStatus::selection_failed,completed};
        if (slot==0) first_batch();
        else singleton();
        if (!validate(slot)) return {MainFamilyDispatchStatus::callback_validation_failed,completed};
        ++completed;
    }
    return {MainFamilyDispatchStatus::complete,completed};
}

template<class View, class Context, class Getter, class Setter>
ScopedMainFamilyMutation(View*,size_t,int32_t&,Context&,Getter,Setter)
    -> ScopedMainFamilyMutation<View,
        std::remove_cvref_t<decltype(std::declval<Getter>()(std::declval<Context&>()))>,
        Context,Getter,Setter>;

} // namespace uevr::quadview
