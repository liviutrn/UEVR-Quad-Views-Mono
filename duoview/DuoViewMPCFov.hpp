#pragma once
// STALKER 2 global viewmodel FOV removal (IsFOVEnabled=0). Kismet read/write
// run only on the game thread, before Unreal draws either DuoView source.
// This game-wide material parameter is NEVER set independently per view.
// The previous TanFOV magnification experiment is intentionally removed.
// Disable restores the observed pre-override value only if still owned here.
#include <array>
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <optional>
#include <string>

#include <sdk/UObjectArray.hpp>
#include <sdk/UGameEngine.hpp>
#include <sdk/UClass.hpp>
#include <sdk/UFunction.hpp>
#include <sdk/FProperty.hpp>
#include <sdk/FFieldClass.hpp>
#include <sdk/FName.hpp>

namespace uevr::duoview::mpc {
constexpr auto collection_name =
    L"MaterialParameterCollection /Game/_Stalker_2/Materials/MPC/MPC_FOV.MPC_FOV";
struct FunctionLayout {
    sdk::UFunction* fn{};
    size_t size{};
    size_t world{}, collection{}, name{}, value{};
    size_t value_bytes{};
};
inline std::optional<FunctionLayout> layout(sdk::UFunction* fn, bool read) {
    if (!fn) return {};
    const size_t size=fn->get_parms_size();
    if (size<28 || size>128) return {};
    auto* world=fn->find_property(L"WorldContextObject");
    auto* collection=fn->find_property(L"Collection");
    auto* name=fn->find_property(L"ParameterName");
    auto* value=fn->find_property(read ? L"ReturnValue" : L"ParameterValue");
    if (!world || !collection || !name || !value || !value->get_class()) return {};
    const auto value_type=value->get_class()->get_name().to_string();
    const size_t value_bytes=value_type==L"FloatProperty" ? 4 :
                             value_type==L"DoubleProperty" ? 8 : 0;
    if (!value_bytes) return {};
    FunctionLayout result{fn,size,static_cast<size_t>(world->get_offset()),
        static_cast<size_t>(collection->get_offset()),
        static_cast<size_t>(name->get_offset()),
        static_cast<size_t>(value->get_offset()),value_bytes};
    const auto fits=[&](size_t off,size_t length) {
        return off<=size && length<=size-off;
    };
    if (!fits(result.world,8) || !fits(result.collection,8) ||
        !fits(result.name,sdk::FName::runtime_size()) ||
        !fits(result.value,result.value_bytes) ||
        result.world==result.collection || result.name==result.value ||
        result.value<result.name+sdk::FName::runtime_size() ||
        result.world>=result.collection || result.collection>=result.name)
        return {};
    return result;
}
class Bridge {
public:
    enum class Status { uninitialized, missing_collection, missing_world_context,
                        function_abi_unavailable, parameter_read_failed, write_readback_failed, confirmed };
    Status status() const { return status_; }
    float baseline() const { return baseline_; }
    float last_value() const { return last_value_; }
    uint64_t writes() const { return writes_; }
    uint64_t rejects() const { return rejects_; }
    uint64_t attempts() const { return attempts_; }

    // Called exactly once per game tick, before the source pair is drawn.
    // If another game system re-enables the FOV effect while we're active,
    // remember that value and disable it again for BOTH views.
    bool apply(bool disable, sdk::UGameEngine* engine) {
        std::scoped_lock lock{mutex_};
        if (!disable && !override_active_) return true;
        ++attempts_;
        if (!select_world(engine) || !resolve()) { ++rejects_; return false; }
        const auto current=read_value();
        if (!current) { status_=Status::parameter_read_failed; ++rejects_; return false; }
        if (disable) {
            if (!override_active_) {
                baseline_=*current;
                baseline_ready_=true;
            } else if (*current > .0005f) {
                // The game refreshed its FOV setting, for example on ADS.
                // Treat that as the new value to restore on mode exit.
                baseline_=*current;
            }
            // Remember ownership only after confirming or explicitly writing
            // zero. An initial game-provided zero is also a valid baseline.
            if (*current > .0005f) {
                // OWNERSHIP MUST BE LATCHED BEFORE the write: ProcessEvent can
                // change the collection even if readback later fails. Without
                // this, mode exit could permanently lose the baseline.
                override_active_=true;
                if (!invoke(*setter_,0.f)) {
                    status_=Status::function_abi_unavailable; ++rejects_; return false;
                }
                ++writes_;
            }
            const auto after=read_value();
            if (!after || std::fabs(*after)>.0005f) {
                status_=Status::write_readback_failed; ++rejects_; return false;
            }
            override_active_=true;
            last_value_=*after;
            status_=Status::confirmed;
            return true;
        }
        // Do not overwrite a value a different system has already changed.
        // Restoration is idempotent, and scoped to the same live controller.
        const float wanted=baseline_ready_ ? baseline_ : *current;
        if (std::fabs(*current)<.0005f && std::fabs(wanted-*current)>.0005f) {
            if (!invoke(*setter_,wanted)) {
                status_=Status::function_abi_unavailable; ++rejects_; return false;
            }
            ++writes_;
            const auto after=read_value();
            if (!after || std::fabs(*after-wanted)>.0005f) {
                status_=Status::write_readback_failed; ++rejects_; return false;
            }
            last_value_=*after;
        } else {
            last_value_=*current;
        }
        override_active_=false;
        baseline_ready_=false;
        status_=Status::confirmed;
        return true;
    }

    bool override_active() const {
        std::scoped_lock lock{mutex_};
        return override_active_;
    }

private:
    sdk::UClass* class_{};
    sdk::UObject* library_{};
    sdk::UObject* collection_{};
    std::optional<sdk::object_liveness::Identity> collection_identity_{};
    sdk::UObject* world_{};
    std::optional<sdk::object_liveness::Identity> world_identity_{};
    std::optional<FunctionLayout> setter_,getter_;
    sdk::OwnedFName parameter_name_{L"IsFOVEnabled"};
    float baseline_{1.f},last_value_{1.f};
    bool baseline_ready_{},last_write_ready_{},override_active_{};
    Status status_{Status::uninitialized};
    uint64_t writes_{},rejects_{},attempts_{};
    mutable std::mutex mutex_{};

    // Read the game thread's ACTUAL active world. The earlier implementation
    // arbitrarily selected the first PlayerController in GUObjectArray and
    // could retain the wrong world over level loads.
    bool select_world(sdk::UGameEngine* engine) {
        if (!engine || !sdk::observe_uobject(engine)) {
            status_=Status::missing_world_context;
            return false;
        }
        const auto* viewport_slot=engine->get_property_data(L"GameViewport");
        if (!viewport_slot) { status_=Status::missing_world_context; return false; }
        auto* viewport=*reinterpret_cast<sdk::UObject* const*>(viewport_slot);
        if (!viewport || !sdk::observe_uobject(viewport)) {
            status_=Status::missing_world_context;
            return false;
        }
        const auto* world_slot=viewport->get_property_data(L"World");
        if (!world_slot) { status_=Status::missing_world_context; return false; }
        auto* candidate=*reinterpret_cast<sdk::UObject* const*>(world_slot);
        if (!candidate) { status_=Status::missing_world_context; return false; }
        const auto observation=sdk::observe_uobject(candidate);
        if (!observation) { status_=Status::missing_world_context; return false; }
        if (candidate!=world_ || !world_identity_ ||
            !sdk::is_current_object(*world_identity_)) {
            // A new world is a new MPC instance: never restore the old
            // world's value into a different level.
            world_=candidate;
            world_identity_=observation->identity;
            baseline_ready_=last_write_ready_=override_active_=false;
        }
        return true;
    }
    bool resolve() {
        // Unreal may unload/recreate the material collection on world changes.
        // Never dereference a cached UObject after its FUObjectArray identity
        // has changed. Retire the old per-world baseline on invalidation.
        if (collection_identity_ && !sdk::is_current_object(*collection_identity_)) {
            collection_=nullptr;
            collection_identity_.reset();
            baseline_ready_=last_write_ready_=override_active_=false;
        }
        if (!collection_) {
            collection_=sdk::find_uobject<sdk::UObject>(collection_name,false);
            if (!collection_) { status_=Status::missing_collection; return false; }
            const auto observation=sdk::observe_uobject(collection_);
            if (!observation) {
                collection_=nullptr;
                status_=Status::missing_collection;
                return false;
            }
            collection_identity_=observation->identity;
        }
        if (!library_) {
            class_=sdk::find_uobject<sdk::UClass>(L"Class /Script/Engine.KismetMaterialLibrary",false);
            if (!class_) { status_=Status::function_abi_unavailable; return false; }
            library_=class_->get_class_default_object();
            setter_=layout(class_->find_function(L"SetScalarParameterValue"),false);
            getter_=layout(class_->find_function(L"GetScalarParameterValue"),true);
            if (!library_ || !setter_ || !getter_) {
                status_=Status::function_abi_unavailable; return false;
            }
        }
        return true;
    }
    std::optional<float> read_value() {
        if (!getter_) return {};
        std::array<std::byte,128> bytes{};
        if (!prepare(*getter_,bytes)) return {};
        library_->process_event(getter_->fn,bytes.data());
        double value{};
        if (getter_->value_bytes==4) {
            float v{};
            std::memcpy(&v,bytes.data()+getter_->value,4);
            value=v;
        } else {
            std::memcpy(&value,bytes.data()+getter_->value,8);
        }
        if (!std::isfinite(value) || value < -.0005 || value > 10.0) return {};
        return static_cast<float>(value);
    }
    bool invoke(const FunctionLayout& fn,float v) {
        std::array<std::byte,128> bytes{};
        if (!prepare(fn,bytes)) return false;
        if (fn.value_bytes==4)
            std::memcpy(bytes.data()+fn.value,&v,4);
        else {
            const double dbl=v;
            std::memcpy(bytes.data()+fn.value,&dbl,8);
        }
        library_->process_event(fn.fn,bytes.data());
        return true;
    }
    bool prepare(const FunctionLayout& fn,std::array<std::byte,128>& bytes) {
        if (!sdk::UObjectBase::try_resolve_process_event_index() || !world_ || !collection_ ||
            !collection_identity_ || !sdk::is_current_object(*collection_identity_) ||
            !world_identity_ || !sdk::is_current_object(*world_identity_))
            return false;
        std::memcpy(bytes.data()+fn.world,&world_,8);
        std::memcpy(bytes.data()+fn.collection,&collection_,8);
        return parameter_name_.write_to(bytes.data()+fn.name,bytes.size()-fn.name);
    }
};
inline Bridge& active() { static Bridge instance; return instance; }
} // namespace uevr::duoview::mpc
