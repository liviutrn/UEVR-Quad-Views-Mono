#pragma once
#include <array>
#include <cstdint>
#include <cstddef>
#include <utility>
#include <mutex>
#include <optional>

namespace uevr::quadview {
// Joins four distinct engine-target executions into the existing delivery
// boundary. The original engine ticket remains live until every tail retires.
template<class Delivery> class NativeDelivery {
public:
    using Source = typename Delivery::Source;
    using EngineTicket = typename Delivery::EngineTicket;
    struct Command {
        Source source{};
        EngineTicket engine{};
        uint64_t target_set{};
        uintptr_t target{};
        uint8_t view{};
        explicit operator bool() const { return bool(source) && bool(engine) && target_set && target && view<4; }
    };
    explicit NativeDelivery(Delivery& delivery): delivery_(delivery) {}
    bool bind(Source source, EngineTicket engine, uint64_t target_set,
              std::array<uintptr_t,4> targets) {
        if (!source || !engine || !target_set || source.generation!=engine.generation ||
            source.serial!=engine.serial || source.engine_frame!=engine.engine_frame ||
            source.family!=engine.family || source.target!=engine.target || source.scene!=engine.scene) return false;
        source.engine_frame_bound=true;
        for (size_t i=0;i<4;++i) {
            if (!targets[i]) return false;
            for(size_t j=0;j<i;++j) if(targets[i]==targets[j]) return false;
        }
        std::scoped_lock lock{mutex_};
        for (const auto& slot: slots_) if(slot.source &&
            slot.source.generation==source.generation && slot.source.serial==source.serial) return false;
        for (auto& slot: slots_) if(!slot.source) {
            slot.source=std::move(source); slot.engine=engine; slot.target_set=target_set; slot.targets=targets;
            return true;
        }
        return false;
    }
    std::optional<Command> render(uint64_t generation, uint32_t frame, uintptr_t target, uintptr_t scene) {
        std::scoped_lock lock{mutex_};
        Slot* match{}; size_t view{};
        for (auto& slot: slots_) if(slot.source && slot.source.generation==generation &&
            slot.source.engine_frame==frame && slot.source.scene==scene) {
            for(size_t i=0;i<4;++i) if(slot.targets[i]==target) {
                if(match) return {};
                match=&slot; view=i;
            }
        }
        if(!match || (match->rendered & (1u<<view))) return {};
        if(!match->rendered) {
            const auto engine=delivery_.render_engine_family(generation,frame,match->source.target,scene);
            const auto source=delivery_.render(generation,frame,match->source.family,match->source.target,scene);
            if(!engine || !engine->same_owner(match->engine)) return {};
            match->publish=source && source->same_owner(match->source);
        }
        match->rendered |= uint8_t(1u<<view);
        return Command{match->source,match->engine,match->target_set,target,uint8_t(view)};
    }
    bool hook(const Command& owner, uintptr_t command) {
        std::scoped_lock lock{mutex_}; auto* slot=find(owner);
        if(!slot || !command || !(slot->rendered&(1u<<owner.view)) || (slot->hooked&(1u<<owner.view))) return false;
        for(auto existing:slot->commands) if(existing==command) return false;
        slot->commands[owner.view]=command; slot->hooked|=uint8_t(1u<<owner.view);
        if(slot->hooked==15) {
            slot->final_command=command;
            if(!delivery_.tail_hooked_engine_family(slot->engine,slot->publish ? slot->source : Source{},command)) return false;
        }
        return true;
    }
    bool executed(const Command& owner, uintptr_t command, uint32_t thread) {
        std::scoped_lock lock{mutex_}; auto* slot=find(owner);
        if(!slot || !thread || !command || slot->commands[owner.view]!=command ||
           (slot->executed&(1u<<owner.view))) return false;
        if(slot->thread && slot->thread!=thread) return false;
        slot->thread=thread;
        // A partially overwritten quartet must never remain available for XR retries.
        delivery_.invalidate_reused_target(slot->source.generation,slot->source.target,slot->source.serial);
        for(auto& other:slots_) if(other.source && other.target_set==slot->target_set &&
            other.source.generation==slot->source.generation && other.source.serial<slot->source.serial)
            other.overwritten=true;
        slot->executed |= uint8_t(1u<<owner.view);
        if(slot->executed!=15) return true;
        const auto source=slot->overwritten || !slot->publish ? Source{} : slot->source;
        const bool retired=delivery_.executed_engine_family(slot->engine,source,slot->final_command,thread);
        if(slot->overwritten) delivery_.retire(slot->source.generation,slot->source.serial);
        if(retired) *slot={};
        return retired;
    }
    void reset() { std::scoped_lock lock{mutex_}; for(auto& slot:slots_) slot={}; }
private:
    struct Slot {
        Source source{}; EngineTicket engine{}; uint64_t target_set{};
        std::array<uintptr_t,4> targets{},commands{};
        uintptr_t final_command{}; uint32_t thread{};
        uint8_t rendered{},hooked{},executed{}; bool overwritten{},publish{true};
    };
    Slot* find(const Command& owner) {
        if(!owner) return nullptr;
        for(auto& slot:slots_) if(slot.source && slot.source.same_owner(owner.source) &&
            slot.engine.same_owner(owner.engine) && slot.target_set==owner.target_set &&
            slot.targets[owner.view]==owner.target) return &slot;
        return nullptr;
    }
    Delivery& delivery_; std::mutex mutex_; std::array<Slot,32> slots_{};
};
}
