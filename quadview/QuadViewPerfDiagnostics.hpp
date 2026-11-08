#pragma once
// B41 opt-in observational profiling. No fences, GPU waits, per-frame allocations
// or lifetime changes in rendering paths.
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>

namespace uevr::quadview::perf {
using Clock=std::chrono::steady_clock;
using Time=Clock::time_point;
struct Summary { uint64_t count{}; double last_ms{},average_ms{},maximum_ms{}; };
struct Counter {
    std::atomic<uint64_t> count{0},sum_us{0},last_us{0},maximum_us{0};
    void add_us(uint64_t us) noexcept {
        last_us.store(us,std::memory_order_relaxed);
        sum_us.fetch_add(us,std::memory_order_relaxed);
        count.fetch_add(1,std::memory_order_relaxed);
        auto old=maximum_us.load(std::memory_order_relaxed);
        while(us>old && !maximum_us.compare_exchange_weak(old,us,
              std::memory_order_relaxed,std::memory_order_relaxed)) {}
    }
    void clear() noexcept {
        count.store(0,std::memory_order_relaxed);
        sum_us.store(0,std::memory_order_relaxed);
        last_us.store(0,std::memory_order_relaxed);
        maximum_us.store(0,std::memory_order_relaxed);
    }
    Summary snapshot() const noexcept {
        Summary s{};
        s.count=count.load(std::memory_order_relaxed);
        s.last_ms=double(last_us.load(std::memory_order_relaxed))/1000.;
        s.maximum_ms=double(maximum_us.load(std::memory_order_relaxed))/1000.;
        if(s.count) s.average_ms=double(sum_us.load(std::memory_order_relaxed))/(1000.*double(s.count));
        return s;
    }
};
inline std::atomic<bool> enabled{false};
inline Counter source_context_cpu,source_left_cpu,source_right_cpu;
inline Counter composite_record_cpu,copy_call_cpu,composite_gpu,seam_analysis_gpu,output_interval;
inline std::atomic<uint64_t> composed{0},copy_failed{0},missing_source{0};
inline std::atomic<int64_t> last_output_ns{0};
inline void reset() noexcept {
    source_context_cpu.clear();source_left_cpu.clear();source_right_cpu.clear();
    composite_record_cpu.clear();copy_call_cpu.clear();composite_gpu.clear();
    seam_analysis_gpu.clear();output_interval.clear();
    composed.store(0,std::memory_order_relaxed);
    copy_failed.store(0,std::memory_order_relaxed);
    missing_source.store(0,std::memory_order_relaxed);
    last_output_ns.store(0,std::memory_order_relaxed);
}
inline void set_enabled(bool on) noexcept {
    enabled.store(false,std::memory_order_release);
    if(on){reset();enabled.store(true,std::memory_order_release);}
}
inline Time begin() noexcept {
    return enabled.load(std::memory_order_relaxed)?Clock::now():Time{};
}
inline uint64_t elapsed_us(Time start) noexcept {
    if(start==Time{})return 0;
    auto us=std::chrono::duration_cast<std::chrono::microseconds>(Clock::now()-start).count();
    return us>0?uint64_t(us):1u;
}
inline void end_role(uint32_t slot,Time start) noexcept {
    if(start==Time{})return;
    auto us=elapsed_us(start);
    if(slot==0)source_context_cpu.add_us(us);
    else if(slot==2)source_left_cpu.add_us(us);
    else if(slot==3)source_right_cpu.add_us(us);
}
inline void end_record(Time start) noexcept {
    if(start!=Time{})composite_record_cpu.add_us(elapsed_us(start));
}
inline void end_copy(Time start) noexcept {
    if(start!=Time{})copy_call_cpu.add_us(elapsed_us(start));
}
inline void retired_gpu(float total_ms,float analysis_ms) noexcept {
    if(!enabled.load(std::memory_order_relaxed))return;
    if(std::isfinite(total_ms)&&total_ms>=0.f&&total_ms<1000.f) {
        composite_gpu.add_us(uint64_t(total_ms*1000.f+0.5f));
        if(std::isfinite(analysis_ms)&&analysis_ms>=0.f&&analysis_ms<1000.f)
            seam_analysis_gpu.add_us(uint64_t(analysis_ms*1000.f+0.5f));
    }
}
inline void output_accepted() noexcept {
    if(!enabled.load(std::memory_order_relaxed))return;
    auto now=std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count();
    auto previous=last_output_ns.exchange(now,std::memory_order_relaxed);
    if(previous>0&&now>previous&&now-previous<1000000000LL)
        output_interval.add_us(uint64_t((now-previous)/1000));
    composed.fetch_add(1,std::memory_order_relaxed);
}
inline void output_failed() noexcept {
    if(enabled.load(std::memory_order_relaxed))copy_failed.fetch_add(1,std::memory_order_relaxed);
}
inline void source_missing() noexcept {
    if(enabled.load(std::memory_order_relaxed))missing_source.fetch_add(1,std::memory_order_relaxed);
}
} // namespace uevr::quadview::perf
