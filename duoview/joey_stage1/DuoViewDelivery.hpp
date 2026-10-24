#pragma once
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <thread>

namespace uevr::duoview {

inline constexpr uint32_t capture_role_primary = 1u << 0;
inline constexpr uint32_t capture_role_secondary = 1u << 1;
inline constexpr uint32_t capture_role_auxiliary = 1u << 2;
inline constexpr uint32_t capture_role_stereo_pair = capture_role_primary | capture_role_secondary;

// Source identity for the RHI-thread interval opened only by the direct
// PreRender view-family checkpoint. Deferred Slate checkpoints deliberately do
// not call begin_direct(), so they cannot relabel earlier depth barriers.
struct CaptureSourceStamp {
    uint64_t generation{};
    uint64_t frame{};
    uint64_t packet_serial{};
    uint32_t role_mask{};
    bool direct_pre_render{};

    constexpr bool valid() const noexcept {
        return generation && frame && packet_serial && direct_pre_render &&
            (role_mask & capture_role_stereo_pair) != 0 &&
            !(role_mask & ~capture_role_stereo_pair);
    }
};

// The direct render-thread checkpoint is attached to one exact UE RHI command.
// It becomes sticky only when that command executes on the RHI thread. The
// bounded command table prevents a delayed/unexecuted callback from being
// mistaken for a later producer packet.
class CaptureSourceStampRegistry {
public:
    static constexpr size_t capacity = 32;
    static constexpr size_t command_capacity = 64;

    bool prepare_direct_command(uintptr_t command, CaptureSourceStamp stamp) {
        if (!command) return false;
        std::scoped_lock lock{mutex_};
        auto* slot = find_command(command);
        if (!stamp.valid()) {
            if (slot) *slot = {};
            return false;
        }
        if (!slot) slot = allocate_command(command);
        if (!slot) return false;
        slot->stamp = stamp;
        slot->last_touch = ++clock_;
        return true;
    }

    CaptureSourceStamp consume_direct_command(uintptr_t command) {
        if (!command) return {};
        std::scoped_lock lock{mutex_};
        for (auto& slot : commands_) {
            if (slot.command == command) {
                const auto stamp = slot.stamp;
                slot = {};
                return stamp;
            }
        }
        return {};
    }

    void begin_direct(uint32_t thread, CaptureSourceStamp stamp) {
        if (!thread) return;
        std::scoped_lock lock{mutex_};
        auto* slot = find_or_allocate(thread);
        if (slot) {
            slot->stamp = stamp.valid() ? stamp : CaptureSourceStamp{};
            slot->last_touch = ++clock_;
        }
    }

    CaptureSourceStamp current(uint32_t thread) const {
        if (!thread) return {};
        std::scoped_lock lock{mutex_};
        for (const auto& slot : slots_) {
            if (slot.thread == thread) return slot.stamp;
        }
        return {};
    }

    void clear(uint32_t thread) {
        if (!thread) return;
        std::scoped_lock lock{mutex_};
        for (auto& slot : slots_) {
            if (slot.thread == thread) {
                slot.stamp = {};
                slot.last_touch = ++clock_;
                return;
            }
        }
    }

    void clear_all() {
        std::scoped_lock lock{mutex_};
        for (auto& slot : slots_) slot.stamp = {};
        for (auto& slot : commands_) slot = {};
    }

    void clear_pending_commands() {
        std::scoped_lock lock{mutex_};
        for (auto& slot : commands_) slot = {};
    }

private:
    struct Slot {
        uint32_t thread{};
        CaptureSourceStamp stamp{};
        uint64_t last_touch{};
    };

    struct CommandSlot {
        uintptr_t command{};
        CaptureSourceStamp stamp{};
        uint64_t last_touch{};
    };

    Slot* find_or_allocate(uint32_t thread) {
        for (auto& slot : slots_) if (slot.thread == thread) return &slot;
        for (auto& slot : slots_) if (!slot.thread) {
            slot.thread = thread;
            return &slot;
        }
        auto* oldest = &slots_[0];
        for (auto& slot : slots_) if (slot.last_touch < oldest->last_touch) oldest = &slot;
        oldest->thread = thread;
        oldest->stamp = {};
        return oldest;
    }

    CommandSlot* find_command(uintptr_t command) {
        for (auto& slot : commands_) if (slot.command == command) return &slot;
        return nullptr;
    }

    CommandSlot* allocate_command(uintptr_t command) {
        for (auto& slot : commands_) if (!slot.command) {
            slot.command = command;
            return &slot;
        }
        auto* oldest = &commands_[0];
        for (auto& slot : commands_) if (slot.last_touch < oldest->last_touch) oldest = &slot;
        oldest->command = command;
        oldest->stamp = {};
        return oldest;
    }

    mutable std::mutex mutex_{};
    std::array<Slot, capacity> slots_{};
    std::array<CommandSlot, command_capacity> commands_{};
    uint64_t clock_{};
};

inline CaptureSourceStampRegistry capture_source_stamps{};

// D3D12 command-list identity is only used while the COM object is retained by
// the observer. A list must have a successful Reset and Close epoch, and must
// be outside a render pass, before depth can be copied. This rejects open,
// bundle, ambiguous and render-pass captures without guessing from resource
// dimensions or a recycled native pointer.
class CommandListEpochRegistry {
public:
    static constexpr size_t capacity = 128;

    struct Epoch {
        uint64_t value{};
        bool known{};
        bool open{};
        bool closed{};
        bool render_pass{};
    };

    Epoch reset(uintptr_t command) {
        if (!command) return {};
        std::scoped_lock lock{mutex_};
        auto* slot = find_or_allocate(command);
        if (!slot) return {};
        ++slot->epoch.value;
        if (!slot->epoch.value) ++slot->epoch.value;
        slot->epoch.known = true;
        slot->epoch.open = true;
        slot->epoch.closed = false;
        slot->epoch.render_pass = false;
        slot->last_touch = ++clock_;
        return slot->epoch;
    }

    void close(uintptr_t command, bool succeeded) {
        update(command, [&](Epoch& epoch) {
            if (succeeded && epoch.known && epoch.open) {
                epoch.open = false;
                epoch.closed = true;
            } else {
                epoch.open = false;
                epoch.closed = false;
            }
        });
    }

    void begin_render_pass(uintptr_t command) {
        update(command, [](Epoch& epoch) { if (epoch.known && epoch.open) epoch.render_pass = true; });
    }

    void end_render_pass(uintptr_t command) {
        update(command, [](Epoch& epoch) { if (epoch.known && epoch.open) epoch.render_pass = false; });
    }

    Epoch current(uintptr_t command) const {
        if (!command) return {};
        std::scoped_lock lock{mutex_};
        for (const auto& slot : slots_) if (slot.command == command) return slot.epoch;
        return {};
    }

    bool can_capture(uintptr_t command) const {
        const auto epoch = current(command);
        return epoch.known && epoch.open && !epoch.closed && !epoch.render_pass;
    }

    void forget(uintptr_t command) {
        std::scoped_lock lock{mutex_};
        for (auto& slot : slots_) if (slot.command == command) { slot = {}; return; }
    }

private:
    struct Slot { uintptr_t command{}; Epoch epoch{}; uint64_t last_touch{}; };

    Slot* find_or_allocate(uintptr_t command) {
        for (auto& slot : slots_) if (slot.command == command) return &slot;
        for (auto& slot : slots_) if (!slot.command) { slot.command = command; return &slot; }
        auto* oldest = &slots_[0];
        for (auto& slot : slots_) if (slot.last_touch < oldest->last_touch) oldest = &slot;
        oldest->command = command;
        oldest->epoch = {};
        return oldest;
    }

    template<class F>
    void update(uintptr_t command, F&& update_epoch) {
        if (!command) return;
        std::scoped_lock lock{mutex_};
        auto* slot = find_or_allocate(command);
        if (!slot) return;
        update_epoch(slot->epoch);
        slot->last_touch = ++clock_;
    }

    mutable std::mutex mutex_{};
    std::array<Slot, capacity> slots_{};
    uint64_t clock_{};
};

using CommandListEpoch = CommandListEpochRegistry::Epoch;

inline CommandListEpochRegistry command_list_epochs{};

enum class SourceRole : uint8_t { primary, secondary, auxiliary };
enum class DeliveryEvent : uint8_t { family, render, hook, duplicate, conflict, execute, select, miss, copy, submit };
struct DeliveryTrace {
    uint64_t sequence{}, time_us{}, generation{}, serial{};
    uintptr_t command{}, target{};
    uint32_t frame{}, thread{};
    DeliveryEvent event{};
    SourceRole role{SourceRole::auxiliary};
    uint64_t draw{}, capture_generation{};
    uint32_t pose{};
};

struct DeliveryCounts {
    uint64_t produced{}, ready{}, matched{}, enqueued{}, submitted{}, duplicate_presents{}, overwritten{}, failed{}, blocked{};
};

template<class Packet, size_t Capacity = 128>
class Delivery {
public:
    struct Source {
        std::shared_ptr<const Packet> packet{};
        uint64_t generation{};
        uintptr_t target{}, scene{};
        uint32_t frame{};
        SourceRole role{SourceRole::auxiliary};
        explicit operator bool() const { return role != SourceRole::auxiliary; }
        bool same_owner(const Source& other) const {
            return generation == other.generation && packet == other.packet &&
                target == other.target && scene == other.scene && frame == other.frame && role == other.role;
        }
    };

    enum class Attachment { added, duplicate, conflict };
    struct Command {
        std::array<Source,2> sources{};
        Source original{};
        Source owner() const { return original; }
        Attachment attach(const Source& source) {
            if (!source) return Attachment::conflict;
            auto& slot=sources[static_cast<size_t>(source.role)];
            if (slot) return slot.same_owner(source) ? Attachment::duplicate : Attachment::conflict;
            const auto existing=owner();
            if (existing && (existing.packet!=source.packet || existing.generation!=source.generation ||
                existing.scene!=source.scene || existing.target==source.target)) return Attachment::conflict;
            slot=source;
            if (!original) original=source;
            return Attachment::added;
        }
    };

    bool family(Source source, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        if (!source || !source.packet || !advance(source.generation) || source.packet->serial<=blocked_serial_) return false;
        targets_[static_cast<size_t>(source.role)] = source.target;
        largest_registered_serial_ = (std::max)(largest_registered_serial_, source.packet->serial);
        for (auto& entry : families_) {
            if (entry && entry.generation == source.generation && entry.frame == source.frame &&
                entry.target == source.target && entry.scene == source.scene) return entry.same_owner(source);
        }
        for (auto& entry : families_) {
            if (!entry) { entry = source; if (source.role==SourceRole::primary) ++counts_.produced; trace(DeliveryEvent::family, source, 0, thread); return true; }
        }
        trace(DeliveryEvent::conflict, source, 0, thread);
        return false;
    }

    Source render(uint64_t generation, uint32_t frame, uintptr_t target, uintptr_t scene, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        if (!advance(generation)) return {};
        for (auto& entry : families_) {
            if (entry && entry.frame == frame && entry.target == target && entry.scene == scene) {
                auto result = entry; entry = {}; trace(DeliveryEvent::render, result, 0, thread); return result;
            }
        }
        Source missing{{}, generation, target, scene, frame,
            target && target == targets_[0] ? SourceRole::primary :
            target && target == targets_[1] ? SourceRole::secondary : SourceRole::auxiliary};
        if (missing) trace(DeliveryEvent::miss, missing, 0, thread);
        return missing;
    }

    void executed(const Source& source, uintptr_t command, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        if (!source || !advance(source.generation) || (source.packet && source.packet->serial<=blocked_serial_)) return;
        const auto& old=sources_[0].packet;
        if (old && old==sources_[1].packet && old!=source.packet && old->serial!=last_submitted_) ++counts_.overwritten;
        const auto index = static_cast<size_t>(source.role);
        sources_[index] = source;
        threads_[index] = thread;
        if (sources_[0].packet && sources_[0].packet==sources_[1].packet && source.packet->serial!=last_ready_) {
            last_ready_=source.packet->serial; ++counts_.ready;
        }
        trace(DeliveryEvent::execute, source, command, thread);
    }

    void block(const Source& source, uintptr_t command, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        if (!source || !advance(source.generation)) return;
        ++counts_.blocked;
        blocked_serial_ = (std::max)(blocked_serial_, source.packet ? source.packet->serial : largest_registered_serial_);
        trace(DeliveryEvent::conflict, source, command, thread);
    }

    std::shared_ptr<const Packet> select(uint64_t generation, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        if (!advance(generation)) return {};
        const auto& a = sources_[0]; const auto& b = sources_[1];
        if (!a.packet || a.packet != b.packet || a.packet->serial <= blocked_serial_ ||
            threads_[0] != thread || threads_[1] != thread) {
            trace(DeliveryEvent::miss, a, 0, thread); return {};
        }
        if (a.packet->serial!=last_matched_) { last_matched_=a.packet->serial; ++counts_.matched; }
        trace(DeliveryEvent::select, a, 0, thread);
        return a.packet;
    }

    void retire(uint64_t generation=0) {
        std::scoped_lock lock{mutex_};
        if (generation && generation<generation_) return;
        if (generation>generation_) advance(generation);
        blocked_serial_=(std::max)(blocked_serial_,largest_registered_serial_);
        families_={}; sources_={}; threads_={}; targets_={};
    }

    DeliveryCounts counts() const { std::scoped_lock lock{mutex_}; return counts_; }
    void reset_counts() { std::scoped_lock lock{mutex_}; counts_={}; }
    void result(DeliveryEvent event, uint64_t serial, bool success, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        if (!success || !serial) ++counts_.failed;
        else if (event==DeliveryEvent::copy && serial!=last_enqueued_) { last_enqueued_=serial; ++counts_.enqueued; }
        else if (event==DeliveryEvent::submit) {
            if (serial!=last_submitted_) { last_submitted_=serial; ++counts_.submitted; }
            else ++counts_.duplicate_presents;
        }
        Source source=sources_[0];
        if (!source.packet || source.packet->serial!=serial) source.packet.reset();
        trace(event, source, 0, thread);
        trace_[(sequence_-1)%trace_.size()].serial=serial;
    }

    void note(DeliveryEvent event, const Source& source, uintptr_t command, uint32_t thread) {
        std::scoped_lock lock{mutex_}; trace(event, source, command, thread);
    }

    std::array<DeliveryTrace, 64> recent() const {
        std::scoped_lock lock{mutex_};
        std::array<DeliveryTrace, 64> result{};
        for (size_t i=0; i<result.size(); ++i) {
            if (sequence_ > i) result[result.size()-1-i] = trace_[(sequence_-1-i)%trace_.size()];
        }
        return result;
    }

private:
    bool advance(uint64_t generation) {
        if (!generation || generation < generation_) return false;
        if (generation != generation_) {
            generation_ = generation; families_ = {}; sources_ = {}; threads_ = {}; targets_ = {};
            blocked_serial_ = 0; largest_registered_serial_ = 0;
            last_ready_=0; last_matched_=0; last_enqueued_=0; last_submitted_=0; counts_={};
        }
        return true;
    }
    void trace(DeliveryEvent event, const Source& source, uintptr_t command, uint32_t thread) {
        const auto us = std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count();
        trace_[sequence_%trace_.size()] = {sequence_+1, static_cast<uint64_t>(us), source.generation,
            source.packet ? source.packet->serial : 0, command, source.target, source.frame, thread, event, source.role};
        if constexpr (requires { source.packet->duoview_frame; source.packet->duoview_mono_source_frame; source.packet->capture_generation; }) {
            auto& event_trace=trace_[sequence_%trace_.size()];
            if (source.packet) {
                event_trace.draw=source.packet->duoview_frame ? source.packet->duoview_frame->config.key.frame : 0;
                event_trace.pose=source.packet->duoview_mono_source_frame;
                event_trace.capture_generation=source.packet->capture_generation;
            }
        }
        ++sequence_;
    }
    mutable std::mutex mutex_{};
    uint64_t generation_{}, sequence_{}, blocked_serial_{}, largest_registered_serial_{};
    uint64_t last_ready_{}, last_matched_{}, last_enqueued_{}, last_submitted_{};
    DeliveryCounts counts_{};
    std::array<Source, Capacity> families_{};
    std::array<Source, 2> sources_{};
    std::array<uintptr_t, 2> targets_{};
    std::array<uint32_t, 2> threads_{};
    std::array<DeliveryTrace, 8192> trace_{};
};

template<class ReadNext>
std::optional<uintptr_t> command_tail(uintptr_t root, ReadNext&& read_next) {
    constexpr size_t maximum_commands = 65536;
    auto current = root;
    for (size_t i=0; current && i<maximum_commands; ++i) {
        const auto next = read_next(current);
        if (!next) return {};
        if (!*next) return current;
        current = *next;
    }
    return {};
}

} // namespace uevr::duoview
