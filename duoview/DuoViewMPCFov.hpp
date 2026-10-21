#pragma once
// STALKER 2 UE5.5: dynamic World Material Parameter Collection (MPC_FOV/TanFOV).
// Uses the game's proven KismetMaterialLibrary UFunctions, NOT the unrelated
// FSceneViewInitOptions.FirstPersonParams native first-person primitive field.
// No private SDK source edits. If reflection or parameter ABI is not verified,
// no ProcessEvent writes occur. Both DuoView views use a shared WORLD MPC;
// distinct per-source visual states remain an experimental timing question.
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

    // Called from the game's producer-side scene-view initialization; NEVER
    // the XR copy callback. Source parameters are frame-frozen by DuoView.
    bool set_factor(float factor, bool enabled) {
        std::scoped_lock _{mutex_};
        if (!enabled && !override_active_) return false;
        ++attempts_;
        if (!std::isfinite(factor) || factor<.33f || factor>3.f) { ++rejects_; return false; }
        if (!resolve()) { ++rejects_; return false; }
        auto actual=read_value();
        if (!actual) { status_=Status::parameter_read_failed; ++rejects_; return false; }
        if (!baseline_ready_) { baseline_=*actual; baseline_ready_=true; }
        else if (last_write_ready_ && std::fabs(*actual-last_value_)>.0005f) {
            // Game-provided transition / ADS value takes precedence.
            baseline_=*actual;
        }
        const float wanted=enabled ? baseline_*factor : baseline_;
        if (!std::isfinite(wanted) || wanted<.05f || wanted>10.f) {
            ++rejects_; return false;
        }
        if (std::fabs(*actual-wanted)<.0005f) {
            last_value_=*actual;
            last_write_ready_=true;
            override_active_=enabled && std::fabs(factor-1.f)>.0005f;
            status_=Status::confirmed;
            return true;
        }
        if (!invoke(*setter_,wanted)) {
            ++rejects_; status_=Status::function_abi_unavailable; return false;
        }
        auto confirmed=read_value();
        if (!confirmed || std::fabs(*confirmed-wanted)>.001f) {
            ++rejects_; status_=Status::write_readback_failed; return false;
        }
        ++writes_;
        last_value_=*confirmed;
        last_write_ready_=true;
        override_active_=enabled && std::fabs(factor-1.f)>.0005f;
        status_=Status::confirmed;
        return true;
    }

private:
    sdk::UClass* class_{};
    sdk::UObject* library_{};
    sdk::UObject* collection_{};
    sdk::UObject* controller_{};
    std::optional<sdk::object_liveness::Identity> controller_identity_{};
    std::optional<FunctionLayout> setter_,getter_;
    sdk::OwnedFName parameter_name_{L"TanFOV"};
    float baseline_{1.f},last_value_{1.f};
    bool baseline_ready_{},last_write_ready_{},override_active_{};
    Status status_{Status::uninitialized};
    uint64_t writes_{},rejects_{},attempts_{};
    std::mutex mutex_{};

    bool resolve() {
        if (!collection_) {
            collection_=sdk::find_uobject<sdk::UObject>(collection_name,false);
            if (!collection_) { status_=Status::missing_collection; return false; }
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
        if (controller_identity_ && !sdk::is_current_object(*controller_identity_)) {
            controller_=nullptr;
            controller_identity_.reset();
            baseline_ready_=last_write_ready_=override_active_=false;
        }
        if (!controller_) {
            auto* klass=sdk::find_uobject<sdk::UClass>(L"Class /Script/Engine.PlayerController",false);
            auto* objects=sdk::FUObjectArray::get();
            if (!klass || !objects) { status_=Status::missing_world_context; return false; }
            const auto count=std::clamp(objects->get_object_count(),0,1500000);
            for(int32_t i=0;i<count;i++) {
                auto* item=objects->get_object(i);
                auto* object=item?item->get_object():nullptr;
                if (!object || !sdk::observe_uobject(object)) continue;
                auto* candidate=reinterpret_cast<sdk::UObject*>(object);
                if (candidate->is_a(klass) && !candidate->is_pending_kill_or_unreachable()) {
                    const auto observation=sdk::observe_uobject(candidate);
                    if (!observation) continue;
                    controller_=candidate;
                    controller_identity_=observation->identity;
                    break;
                }
            }
            if (!controller_) { status_=Status::missing_world_context; return false; }
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
        if (!std::isfinite(value) || value<.05 || value>10.0) return {};
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
        if (!sdk::UObjectBase::try_resolve_process_event_index() || !controller_ || !collection_ ||
            !controller_identity_ || !sdk::is_current_object(*controller_identity_))
            return false;
        std::memcpy(bytes.data()+fn.world,&controller_,8);
        std::memcpy(bytes.data()+fn.collection,&collection_,8);
        return parameter_name_.write_to(bytes.data()+fn.name,bytes.size()-fn.name);
    }
};
inline Bridge& active() { static Bridge instance; return instance; }
} // namespace uevr::duoview::mpc
