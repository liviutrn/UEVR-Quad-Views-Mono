#pragma once

#include <array>
#include <atomic>
#include <cstdint>
#include <cstddef>
#include <mutex>
#include <optional>
#include <type_traits>

namespace uevr::quadview {

// Identifies one explicitly bracketed Slate-worker drain. The list pointer is
// retained alongside the unique drain token; a reused command-list address in
// a later execute() call therefore cannot establish shared-tail provenance.
class NativeDrainScope {
public:
    struct Identity { uint64_t id{}; uintptr_t immediate_list{}; };

    explicit NativeDrainScope(uintptr_t immediate_list) : previous_{current()} {
        if (immediate_list) {
            auto id=next_id_.fetch_add(1,std::memory_order_relaxed)+1;
            if (!id) id=next_id_.fetch_add(1,std::memory_order_relaxed)+1;
            current_id_=id;
            current_list_=immediate_list;
        } else { current_id_=0; current_list_=0; }
    }
    NativeDrainScope(const NativeDrainScope&)=delete;
    NativeDrainScope& operator=(const NativeDrainScope&)=delete;
    ~NativeDrainScope() { current_id_=previous_.id; current_list_=previous_.immediate_list; }

    static Identity current() { return {current_id_,current_list_}; }

private:
    inline static std::atomic<uint64_t> next_id_{};
    inline static thread_local uint64_t current_id_{};
    inline static thread_local uintptr_t current_list_{};
    Identity previous_{};
};

// Joins per-view renderer owners at the RHI tail that actually executes them.
// A tail can represent several roles only when the generated adapter supplies
// the same validated Slate-worker drain and immediate-list identity.  When
// those identities differ, or two quartets meet at one tail, the owners are
// still drained together but none of their source packets can be published.
template<class Delivery> class NativeDelivery {
public:
    using Source = typename Delivery::Source;
    using EngineTicket = typename Delivery::EngineTicket;

    // Fixed scalar summary; never copies a source, command, or packet owner.
    // Counts are sampled under one try-lock and may independently be busy.
    struct DiagnosticsSnapshot {
        uint64_t generation{};
        uint32_t occupied_slots{};
        uint32_t active_tails{};
        uint32_t shared_tails{};
        uint32_t ambiguous_tails{};
        uint64_t oldest_retained_generation{};
        uint64_t oldest_retained_serial{};
        std::array<uint32_t,4> oldest_retained_pending_count{};
        uint8_t oldest_retained_rendered{};
        uint8_t oldest_retained_hooked{};
        uint8_t oldest_retained_executed{};
        uint8_t oldest_retained_written{};
        bool oldest_retained_completion_latched{};
        bool oldest_retained_publish{};
        bool oldest_retained_overwritten{};
        bool oldest_retained_found{};
        bool busy{};
    };
    static_assert(std::is_trivially_copyable_v<DiagnosticsSnapshot>);

    struct Command {
        Source source{};
        EngineTicket engine{};
        uint64_t target_set{};
        uintptr_t target{};
        uint8_t view{};
        explicit operator bool() const {
            return bool(source) && bool(engine) && target_set && target && view < 4;
        }
    };

    struct TailTicket {
        uintptr_t command{};
        uint64_t id{};
        explicit operator bool() const { return command && id; }
    };

    struct RuntimeEvent {
        uint64_t generation{}, serial{};
        uint32_t frame{};
        explicit operator bool() const { return generation && serial; }
    };

    // Retained by the production RHI adapter from queueing until the original
    // command callback returns. NativeDelivery::reset() can retire ledger
    // slots while the CPU command is still queued, so the callback's map
    // record must independently keep each represented packet alive.
    struct TailOwnerBatch {
        static constexpr size_t capacity = 32; // same bound as live quartet slots
        TailTicket ticket{};
        std::array<Command,capacity> owners{};
        size_t owner_count{};

        bool retain(const Command& owner, TailTicket tail) {
            if (!owner || !tail || (ticket && (ticket.command != tail.command || ticket.id != tail.id)))
                return false;
            if (!ticket) ticket = tail;
            for (size_t i=0; i<owner_count; ++i) {
                const auto& existing=owners[i];
                if (existing.source.same_owner(owner.source) &&
                    existing.engine.same_owner(owner.engine) &&
                    existing.target_set==owner.target_set) return true;
            }
            if (owner_count==owners.size()) return false;
            owners[owner_count++]=owner;
            return true;
        }
    };

    enum class AttachStatus : uint8_t { attached, duplicate, quarantined, overflow, rejected };

    struct AttachResult {
        TailTicket tail{};
        AttachStatus status{AttachStatus::rejected};
        explicit operator bool() const {
            return bool(tail) && (status == AttachStatus::attached ||
                status == AttachStatus::duplicate || status == AttachStatus::quarantined);
        }
        bool publishable() const { return status == AttachStatus::attached || status == AttachStatus::duplicate; }
    };

    struct ExecutionResult {
        bool accepted{};
        bool quarantined{};
        uint32_t sync_frame{};
        uint64_t newest_serial{};
        uint8_t completed_quartets{};
        RuntimeEvent runtime_event{};
    };

    explicit NativeDelivery(Delivery& delivery): delivery_{delivery} {}

    DiagnosticsSnapshot diagnostics_snapshot(uint64_t generation = 0) const {
        DiagnosticsSnapshot result{};
        result.generation = generation;
        std::unique_lock<std::mutex> lock;
        try { lock = std::unique_lock<std::mutex>{mutex_, std::try_to_lock}; }
        catch (...) { result.busy = true; return result; }
        if (!lock.owns_lock()) {
            result.busy = true;
            return result;
        }
        for (const auto& slot : slots_) {
            if (!slot.source || (generation && slot.source.generation != generation)) continue;
            ++result.occupied_slots;
            if (!result.oldest_retained_found ||
                slot.source.generation < result.oldest_retained_generation ||
                (slot.source.generation == result.oldest_retained_generation &&
                 slot.source.serial < result.oldest_retained_serial)) {
                result.oldest_retained_found = true;
                result.oldest_retained_generation = slot.source.generation;
                result.oldest_retained_serial = slot.source.serial;
                result.oldest_retained_rendered = slot.rendered;
                result.oldest_retained_hooked = slot.hooked;
                result.oldest_retained_executed = slot.executed;
                result.oldest_retained_written = slot.written;
                result.oldest_retained_pending_count = slot.pending_count;
                result.oldest_retained_completion_latched = slot.completion_latched;
                result.oldest_retained_publish = slot.publish;
                result.oldest_retained_overwritten = slot.overwritten;
            }
        }
        for (const auto& tail : tails_) {
            if (!tail.command) continue;
            bool belongs = false;
            for (size_t i = 0; i < tail.attachment_count; ++i) {
                const auto& participant = tail.attachments[i];
                if (participant.slot >= slots_.size()) continue;
                const auto& slot = slots_[participant.slot];
                if (slot.owner_id != participant.owner_id || !slot.source ||
                    (generation && slot.source.generation != generation)) continue;
                belongs = true;
                break;
            }
            if (!belongs) continue;
            ++result.active_tails;
            bool shared = tail.attachment_count > 1;
            for (size_t i = 0; !shared && i < tail.attachment_count; ++i) {
                const auto mask = tail.attachments[i].view_mask;
                shared = mask != 0 && (mask & uint8_t(mask - 1)) != 0;
            }
            if (shared) ++result.shared_tails;
            if (tail.ambiguous) ++result.ambiguous_tails;
        }
        return result;
    }

    bool bind(Source source, EngineTicket engine, uint64_t target_set,
              std::array<uintptr_t,4> targets) {
        if (!source || !engine || !target_set || source.generation != engine.generation ||
            source.serial != engine.serial || source.engine_frame != engine.engine_frame ||
            source.family != engine.family || source.target != engine.target ||
            source.scene != engine.scene) return false;
        source.engine_frame_bound = true;
        for (size_t i = 0; i < 4; ++i) {
            if (!targets[i]) return false;
            for (size_t j = 0; j < i; ++j) if (targets[i] == targets[j]) return false;
        }
        std::scoped_lock lock{mutex_};
        for (const auto& slot : slots_) if (slot.source &&
            slot.source.generation == source.generation && slot.source.serial == source.serial) return false;
        for (auto& slot : slots_) if (!slot.source) {
            auto owner_id = ++next_owner_id_;
            if (!owner_id) owner_id = ++next_owner_id_;
            slot.source = std::move(source);
            slot.engine = engine;
            slot.target_set = target_set;
            slot.targets = targets;
            slot.owner_id = owner_id;
            return true;
        }
        return false;
    }

    std::optional<Command> render(uint64_t generation, uint32_t frame, uintptr_t target, uintptr_t scene) {
        std::scoped_lock lock{mutex_};
        Slot* match{};
        size_t view{};
        for (auto& slot : slots_) if (slot.source && slot.source.generation == generation &&
            slot.source.engine_frame == frame && slot.source.scene == scene) {
            for (size_t i = 0; i < 4; ++i) if (slot.targets[i] == target) {
                if (match) return {};
                match = &slot;
                view = i;
            }
        }
        if (!match || (match->rendered & (1u << view))) return {};
        if (!match->rendered) {
            const auto engine = delivery_.render_engine_family(
                generation, frame, match->source.target, scene);
            const auto source = delivery_.render(
                generation, frame, match->source.family, match->source.target, scene);
            if (!engine || !engine->same_owner(match->engine)) return {};
            match->publish = source && source->same_owner(match->source);
        }
        match->rendered |= uint8_t(1u << view);
        return Command{match->source, match->engine, match->target_set, target, uint8_t(view)};
    }

    // Compatibility entry point for the existing distinct-tail path and
    // portable ownership tests. Shared tails without an explicit validated
    // drain/list identity are attached as drain-only.
    bool hook(const Command& owner, uintptr_t command) {
        const auto result = hook_batch(owner, command, 0, 0, owner.source.engine_frame);
        return result.status == AttachStatus::attached || result.status == AttachStatus::quarantined;
    }

    AttachResult hook_batch(const Command& owner, uintptr_t command,
                            uint64_t drain_id, uintptr_t immediate_list,
                            uint32_t sync_frame) {
        std::scoped_lock lock{mutex_};
        const auto owner_index = find_index(owner);
        if (!owner || !command || owner_index == slots_.size()) return {};
        auto& owner_slot = slots_[owner_index];
        if (!(owner_slot.rendered & (1u << owner.view))) return {};

        auto* tail = find_tail(command);
        if (!tail) tail = allocate_tail(command, drain_id, immediate_list);
        if (!tail) {
            owner_slot.publish = false;
            owner_slot.overwritten = true;
            return {{}, AttachStatus::overflow};
        }

        const bool has_attachment = tail->attachment_count != 0;
        const bool scope_valid = drain_id != 0 && immediate_list != 0;
        const bool same_scope = scope_valid && tail->drain_id == drain_id &&
            tail->immediate_list == immediate_list;

        auto* participant = find_participant(*tail, owner_index, owner_slot.owner_id);
        if (participant && (participant->view_mask & (1u << owner.view))) {
            return {{command, tail->id}, tail->ambiguous ? AttachStatus::quarantined : AttachStatus::duplicate};
        }

        if (has_attachment && (!same_scope || !tail->scope_valid)) {
            poison_tail(*tail);
        }

        if (has_attachment) {
            for (size_t i = 0; i < tail->attachment_count; ++i) {
                const auto index = tail->attachments[i].slot;
                if (index >= slots_.size()) continue;
                const auto& existing = slots_[index];
                if (!existing.source.same_owner(owner_slot.source) ||
                    existing.target_set != owner_slot.target_set || existing.targets != owner_slot.targets) {
                    poison_tail(*tail);
                    break;
                }
            }
        }

        if (participant == nullptr) {
            if (tail->attachment_count == tail->attachments.size()) {
                poison_tail(*tail);
                owner_slot.publish = false;
                owner_slot.overwritten = true;
                return {{command, tail->id}, AttachStatus::quarantined};
            }
            participant = &tail->attachments[tail->attachment_count++];
            participant->slot = uint8_t(owner_index);
            participant->owner_id = owner_slot.owner_id;
        }

        // One renderer role may not be assigned two independent tails. Keep
        // both owners drainable, but reject content publication for the draw.
        if (owner_slot.hooked & (1u << owner.view)) {
            owner_slot.publish = false;
            owner_slot.overwritten = true;
            participant->view_mask |= uint8_t(1u << owner.view);
        } else {
            participant->view_mask |= uint8_t(1u << owner.view);
        }
        owner_slot.hooked |= uint8_t(1u << owner.view);
        // Tail storage bounds simultaneous pending attachments, but repeated
        // malformed callbacks could otherwise wrap cumulative byte counters.
        // Track only outstanding tails; each execution decrements one.
        if (owner_slot.pending_count[owner.view] == UINT32_MAX) {
            poison_slot(owner_slot);
            return {{command, tail->id}, AttachStatus::overflow};
        }
        ++owner_slot.pending_count[owner.view];
        owner_slot.executed &= uint8_t(~(1u << owner.view));
        if (!scope_valid) {
            tail->scope_valid = false;
            if (tail->attachment_count > 1) poison_tail(*tail);
        }
        // Runtime cadence belongs to the canonical view-3 callback. Other
        // native roles still attach/drain, but never advance OpenXR state.
        if (owner.view == 3 && (!tail->runtime_event ||
            owner_slot.source.generation > tail->runtime_event.generation ||
            (owner_slot.source.generation == tail->runtime_event.generation &&
             owner_slot.source.serial > tail->runtime_event.serial))) {
            tail->runtime_event={owner_slot.source.generation,owner_slot.source.serial,sync_frame};
        }

        if (tail->ambiguous) {
            owner_slot.publish = false;
            owner_slot.overwritten = true;
        }

        latch_completion(owner_slot);
        return {{command, tail->id}, tail->ambiguous ? AttachStatus::quarantined : AttachStatus::attached};
    }

    uint32_t sync_frame(const TailTicket& ticket) const {
        std::scoped_lock lock{mutex_};
        const auto* tail = find_tail(ticket);
        return tail && tail->runtime_event ? tail->runtime_event.frame : 0;
    }

    RuntimeEvent runtime_event(const TailTicket& ticket) const {
        std::scoped_lock lock{mutex_};
        const auto* tail=find_tail(ticket);
        return tail ? tail->runtime_event : RuntimeEvent{};
    }

    bool claim_runtime_event(const TailTicket& ticket,RuntimeEvent& event) {
        std::scoped_lock lock{mutex_};
        const auto* tail=find_tail(ticket);
        if (!tail || !tail->runtime_event) return false;
        const auto candidate=tail->runtime_event;
        if (candidate.generation==last_runtime_generation_ &&
            candidate.serial<=last_runtime_serial_) return false;
        if (candidate.generation<last_runtime_generation_) return false;
        last_runtime_generation_=candidate.generation;
        last_runtime_serial_=candidate.serial;
        event=candidate;
        return true;
    }

    ExecutionResult executed_tail(const TailTicket& ticket, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        auto* tail = find_tail(ticket);
        if (!tail || !thread || tail->executed) return {};
        for (size_t i = 0; i < tail->attachment_count; ++i) {
            const auto index = tail->attachments[i].slot;
            if (index < slots_.size() && slots_[index].owner_id == tail->attachments[i].owner_id &&
                slots_[index].source &&
                slots_[index].thread && slots_[index].thread != thread) return {};
        }
        tail->executed = true;
        ExecutionResult result{};
        result.accepted=true;
        result.quarantined=tail->ambiguous;
        result.sync_frame=tail->runtime_event ? tail->runtime_event.frame : 0;
        result.newest_serial=tail->runtime_event ? tail->runtime_event.serial : 0;
        result.runtime_event=tail->runtime_event;
        for (size_t i = 0; i < tail->attachment_count; ++i) {
            const auto index = tail->attachments[i].slot;
            if (index < slots_.size() && slots_[index].owner_id == tail->attachments[i].owner_id &&
                slots_[index].source) slots_[index].thread = thread;
        }

        if (tail->ambiguous) {
            invalidate_ambiguous_tail(*tail);
        } else {
            for (size_t i = 0; i < tail->attachment_count; ++i) {
                const auto participant = tail->attachments[i];
                if (participant.slot >= slots_.size()) continue;
                auto& slot = slots_[participant.slot];
                if (slot.owner_id != participant.owner_id || !slot.source) continue;
                for (size_t view = 0; view < 4; ++view) {
                    if ((participant.view_mask & (1u << view)) == 0) continue;
                    record_write(participant.slot, view);
                    if (slot.pending_count[view] != 0) {
                        --slot.pending_count[view];
                        if (slot.pending_count[view] == 0) slot.executed |= uint8_t(1u << view);
                    }
                }
            }
        }

        // A poisoned shared tail still drains every owner it actually covers.
        // Its content is untrusted, so role completion advances without
        // creating a selectable packet.
        if (tail->ambiguous) {
            for (size_t i = 0; i < tail->attachment_count; ++i) {
                const auto participant = tail->attachments[i];
                if (participant.slot >= slots_.size()) continue;
                auto& slot = slots_[participant.slot];
                if (slot.owner_id != participant.owner_id || !slot.source) continue;
                for (size_t view = 0; view < 4; ++view) {
                    if ((participant.view_mask & (1u << view)) == 0) continue;
                    if (slot.pending_count[view] != 0) {
                        --slot.pending_count[view];
                        if (slot.pending_count[view] == 0) slot.executed |= uint8_t(1u << view);
                    }
                }
            }
        }

        std::array<bool, 32> seen{};
        for (size_t i = 0; i < tail->attachment_count; ++i) {
            const auto index = tail->attachments[i].slot;
            if (index >= slots_.size() || seen[index] ||
                slots_[index].owner_id != tail->attachments[i].owner_id) continue;
            seen[index] = true;
            auto& slot = slots_[index];
            if (slot.source && slot.executed == 0x0f && finish_quartet(slot, thread))
                ++result.completed_quartets;
        }
        *tail = {};
        return result;
    }

    // Existing distinct-tail entry point. It deliberately executes one tail
    // record, which may also contain other validated same-drain attachments.
    bool executed(const Command& owner, uintptr_t command, uint32_t thread) {
        TailTicket ticket{};
        {
            std::scoped_lock lock{mutex_};
            const auto owner_index = find_index(owner);
            const auto* tail = find_tail(command);
            if (!tail || owner_index == slots_.size()) return false;
            const auto* participant = find_participant(*tail, owner_index, slots_[owner_index].owner_id);
            if (!participant || (participant->view_mask & (1u << owner.view)) == 0) return false;
            ticket = {command, tail->id};
        }
        return executed_tail(ticket, thread).accepted;
    }

    void reset() {
        std::scoped_lock lock{mutex_};
        for (auto& slot : slots_) slot = {};
        for (auto& tail : tails_) tail = {};
        for (auto& stamp : content_) stamp = {};
        last_runtime_generation_=last_runtime_serial_=0;
    }

private:
    static constexpr size_t quartet_capacity = 32;
    static constexpr size_t tail_capacity = quartet_capacity * 4;
    static constexpr size_t target_capacity = quartet_capacity * 4;

    struct Slot {
        Source source{};
        EngineTicket engine{};
        uint64_t target_set{}, owner_id{};
        std::array<uintptr_t,4> targets{};
        std::array<uint32_t,4> pending_count{};
        uintptr_t completion_token{};
        uint32_t thread{};
        uint8_t rendered{}, hooked{}, executed{}, written{};
        bool overwritten{}, publish{true}, completion_latched{};
    };
    struct Participant { uint8_t slot{}; uint8_t view_mask{}; uint64_t owner_id{}; };
    struct Tail {
        uintptr_t command{};
        uint64_t id{}, drain_id{};
        uintptr_t immediate_list{};
        RuntimeEvent runtime_event{};
        std::array<Participant,quartet_capacity> attachments{};
        uint8_t attachment_count{};
        bool scope_valid{}, ambiguous{}, executed{};
    };
    struct ContentStamp {
        uintptr_t target{};
        uint64_t target_set{}, generation{}, serial{};
        uint32_t engine_frame{};
        uintptr_t family{}, source_target{}, scene{};
        std::array<uintptr_t,4> views{};
        bool valid{};
    };

    size_t find_index(const Command& owner) const {
        if (!owner) return slots_.size();
        for (size_t i = 0; i < slots_.size(); ++i) {
            const auto& slot = slots_[i];
            if (slot.source && slot.source.same_owner(owner.source) &&
                slot.engine.same_owner(owner.engine) && slot.target_set == owner.target_set &&
                owner.view < 4 && slot.targets[owner.view] == owner.target) return i;
        }
        return slots_.size();
    }
    Tail* find_tail(uintptr_t command) {
        for (auto& tail : tails_) if (tail.command == command && !tail.executed) return &tail;
        return nullptr;
    }
    const Tail* find_tail(uintptr_t command) const {
        for (const auto& tail : tails_) if (tail.command == command && !tail.executed) return &tail;
        return nullptr;
    }
    Tail* find_tail(const TailTicket& ticket) {
        for (auto& tail : tails_) if (tail.command == ticket.command && tail.id == ticket.id) return &tail;
        return nullptr;
    }
    const Tail* find_tail(const TailTicket& ticket) const {
        for (const auto& tail : tails_) if (tail.command == ticket.command && tail.id == ticket.id) return &tail;
        return nullptr;
    }
    Tail* allocate_tail(uintptr_t command, uint64_t drain_id,
                        uintptr_t immediate_list) {
        for (auto& tail : tails_) if (!tail.command) {
            auto id = ++next_tail_id_;
            if (!id) id = ++next_tail_id_;
            tail.command = command;
            tail.id = id;
            tail.drain_id = drain_id;
            tail.immediate_list = immediate_list;
            tail.scope_valid = drain_id != 0 && immediate_list != 0;
            return &tail;
        }
        return nullptr;
    }
    Participant* find_participant(Tail& tail, size_t slot, uint64_t owner_id) {
        for (size_t i = 0; i < tail.attachment_count; ++i)
            if (tail.attachments[i].slot == slot && tail.attachments[i].owner_id == owner_id)
                return &tail.attachments[i];
        return nullptr;
    }
    const Participant* find_participant(const Tail& tail, size_t slot, uint64_t owner_id) const {
        for (size_t i = 0; i < tail.attachment_count; ++i)
            if (tail.attachments[i].slot == slot && tail.attachments[i].owner_id == owner_id)
                return &tail.attachments[i];
        return nullptr;
    }
    void poison_slot(Slot& slot) {
        if (!slot.source) return;
        slot.publish = false;
        slot.overwritten = true;
        delivery_.retire(slot.source.generation, slot.source.serial);
    }
    void poison_tail(Tail& tail) {
        tail.ambiguous = true;
        for (size_t i = 0; i < tail.attachment_count; ++i) {
            const auto index = tail.attachments[i].slot;
            if (index < slots_.size() && slots_[index].owner_id == tail.attachments[i].owner_id)
                poison_slot(slots_[index]);
        }
    }
    void latch_completion(Slot& slot) {
        if (slot.completion_latched) return;
        if (slot.hooked != 0x0f) return;
        slot.completion_latched = true;
        auto token = ++next_completion_token_;
        if (!token) token = ++next_completion_token_;
        slot.completion_token = static_cast<uintptr_t>(token);
        const bool source_attached = slot.publish && delivery_.tail_hooked_engine_family(
            slot.engine, slot.source, slot.completion_token);
        if (!source_attached) {
            // The ordinary source ledger may have reclaimed this packet after
            // render(). Preserve engine-ticket drainage, but never advertise a
            // completion token as publishable when only the empty fallback fit.
            slot.publish = false;
            slot.overwritten = true;
            if (!delivery_.tail_hooked_engine_family(slot.engine, Source{}, slot.completion_token)) {
                slot.overwritten = true;
            }
        }
    }
    static bool stamp_matches(const ContentStamp& stamp, const Slot& slot) {
        return stamp.valid && stamp.target_set == slot.target_set &&
            stamp.generation == slot.source.generation && stamp.serial == slot.source.serial &&
            stamp.engine_frame == slot.source.engine_frame && stamp.family == slot.source.family &&
            stamp.source_target == slot.source.target && stamp.scene == slot.source.scene &&
            stamp.views == slot.source.view_ids;
    }
    ContentStamp* find_content(uintptr_t target) {
        for (auto& stamp : content_) if (stamp.target == target) return &stamp;
        for (auto& stamp : content_) if (!stamp.target) {
            stamp.target = target;
            return &stamp;
        }
        for (auto& stamp : content_) {
            if (target_is_live(stamp.target)) continue;
            // The source may still be selectable even though its quartet has
            // drained. Evicting provenance must evict that source too, or the
            // Delivery ledger could later return a packet for unknown pixels.
            if (stamp.valid) delivery_.retire(stamp.generation, stamp.serial);
            stamp = {};
            stamp.target = target;
            return &stamp;
        }
        return nullptr;
    }
    const ContentStamp* find_content(uintptr_t target) const {
        for (const auto& stamp : content_) if (stamp.target == target) return &stamp;
        return nullptr;
    }
    bool target_is_live(uintptr_t target) const {
        if (!target) return false;
        for (const auto& slot : slots_) {
            if (!slot.source) continue;
            for (const auto candidate : slot.targets) if (candidate == target) return true;
        }
        return false;
    }
    bool content_matches(const Slot& slot) const {
        for (const auto target : slot.targets) {
            const auto* stamp = find_content(target);
            if (!stamp || !stamp_matches(*stamp, slot)) return false;
        }
        return true;
    }
    void invalidate_resource(uintptr_t target, const Slot* writer) {
        auto* stamp = find_content(target);
        if (stamp) {
            const bool same_writer = writer && stamp_matches(*stamp, *writer);
            if (stamp->valid && !same_writer)
                delivery_.retire(stamp->generation, stamp->serial);
            stamp->valid = false;
        }
        for (auto& candidate : slots_) {
            if (!candidate.source) continue;
            if (writer && candidate.source.same_owner(writer->source)) continue;
            bool wrote_target{};
            for (size_t i = 0; i < candidate.targets.size(); ++i) {
                if (candidate.targets[i] == target && (candidate.written & (1u << i))) {
                    wrote_target = true;
                    break;
                }
            }
            // A queued quartet has no physical content to invalidate yet.
            // Only a writer that has already touched this target can have
            // become incoherent due to this new write.
            if (!wrote_target) continue;
            poison_slot(candidate);
        }
    }
    void record_write(size_t index, size_t view) {
        auto& writer = slots_[index];
        const auto target = writer.targets[view];
        if (!target) return;
        writer.written |= uint8_t(1u << view);
        invalidate_resource(target, &writer);
        if (!writer.publish || writer.overwritten) {
            delivery_.retire(writer.source.generation, writer.source.serial);
            return;
        }
        auto* stamp = find_content(target);
        if (!stamp) {
            poison_slot(writer);
            return;
        }
        *stamp = ContentStamp{target, writer.target_set, writer.source.generation,
            writer.source.serial, writer.source.engine_frame, writer.source.family,
            writer.source.target, writer.source.scene, writer.source.view_ids, true};
    }
    void invalidate_ambiguous_tail(const Tail& tail) {
        for (size_t i = 0; i < tail.attachment_count; ++i) {
            const auto index = tail.attachments[i].slot;
            if (index >= slots_.size() || slots_[index].owner_id != tail.attachments[i].owner_id ||
                !slots_[index].source) continue;
            auto& slot = slots_[index];
            for (size_t view = 0; view < slot.targets.size(); ++view) {
                if (tail.attachments[i].view_mask & (1u << view))
                    record_write(index, view);
            }
            poison_slot(slot);
        }
    }
    bool finish_quartet(Slot& slot, uint32_t thread) {
        if (!slot.completion_latched || !thread || !slot.completion_token) return false;
        const bool coherent = slot.publish && !slot.overwritten && content_matches(slot);
        const auto source = coherent ? slot.source : Source{};
        const bool retired = delivery_.executed_engine_family(
            slot.engine, source, slot.completion_token, thread);
        if (!coherent) delivery_.retire(slot.source.generation, slot.source.serial);
        if (retired) slot = {};
        return retired;
    }

    Delivery& delivery_;
    mutable std::mutex mutex_{};
    std::array<Slot,quartet_capacity> slots_{};
    std::array<Tail,tail_capacity> tails_{};
    std::array<ContentStamp,target_capacity> content_{};
    uint64_t next_tail_id_{}, next_completion_token_{}, next_owner_id_{};
    uint64_t last_runtime_generation_{},last_runtime_serial_{};
};
}
