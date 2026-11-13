#pragma once
// Research #21 bounded CSV trace, off by default. The producer does only
// one bounded atomic-slot write; a dedicated thread owns all disk I/O.
// No Engine/UEVR/OpenXR dependency. Do not use for input or scheduling.
#include <atomic>
#include <array>
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>
#include <filesystem>
#include <fstream>
#include <thread>

namespace research_trace21 {

constexpr std::size_t kLimit = 65536;
enum Kind : std::uint32_t { kGameTick=1, kRender=2, kPose=3, kSubmit=4, kXrWait=5, kXrRealEnd=6 };
struct Row {
    std::atomic<bool> ready{false};
    std::uint32_t kind{0};
    std::uint64_t frame{0};       // UEVR pipeline-frame ID, not guaranteed GFrameNumber
    std::uint64_t secondary{0};   // UEVR render-frame ID or VectorXR real ID
    std::uint64_t tick{0};        // monotonically numbered engine ticks on UEVR
    std::int64_t qpc_ns{0};       // steady_clock MSVC/QPC-equivalent epoch
    std::int64_t display_xr{0};   // XrTime of original predicted/submitted frame
    std::int64_t pose_xr{0};      // XrTime actually passed to xrLocateViews, if known
    std::int64_t aux{0};          // DeltaTime ns or VectorXR target world label
};
class Csv {
    std::array<Row,kLimit> rows_{};
    std::atomic<std::size_t> count_{0};
    std::atomic<bool> stopping_{false};
    std::atomic<std::uint64_t> tick_{0};
    bool enabled_{false};
    std::thread worker_;

    static std::int64_t NowNs() {
        return std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count();
    }
    void Write() {
        try {
            const char* local=std::getenv("LOCALAPPDATA");
            if (!local || !*local) return;
            const auto dir=std::filesystem::path(local)/"VectorXR";
            std::filesystem::create_directories(dir);
#if defined(RESEARCH21_UEVR)
            const auto path=dir/"uevr-world-trace21.csv";
#else
            const auto path=dir/"vectorxr-real-trace21.csv";
#endif
            std::ofstream out(path, std::ios::trunc);
            if (!out) return;
            out<<"kind,frame,secondary,tick,qpc_ns,display_xr,pose_xr,aux\n";
            std::size_t next=0;
            while (!stopping_.load(std::memory_order_acquire) || next<count_.load(std::memory_order_acquire)) {
                std::size_t drained=0;
                const auto n=std::min(count_.load(std::memory_order_acquire), kLimit);
                while (next<n && rows_[next].ready.load(std::memory_order_acquire)) {
                    const auto& r=rows_[next++];
                    out<<r.kind<<','<<r.frame<<','<<r.secondary<<','<<r.tick<<','
                       <<r.qpc_ns<<','<<r.display_xr<<','<<r.pose_xr<<','<<r.aux<<'\n';
                    ++drained;
                }
                if (drained) out.flush();
                if (!drained) std::this_thread::sleep_for(std::chrono::milliseconds(200));
                if (next==kLimit) break; // bounded, never overwrite a reader
            }
            out.flush();
        } catch (...) { /* Research only: never crash game from file I/O. */ }
    }
public:
    explicit Csv(const char* enable_key) {
        const char* p=std::getenv(enable_key);
        enabled_=p && std::strcmp(p,"1")==0;
        if (!p) {
            try {
                const char* home=std::getenv("LOCALAPPDATA");
                if (home && *home) {
                    std::ifstream cfg(std::filesystem::path(home)/"VectorXR"/"framegen-research.txt");
                    std::string line;
                    const std::string key=std::string(enable_key)+"=";
                    while (std::getline(cfg,line)) {
                        if (line.rfind(key,0)==0) { enabled_=(line.substr(key.size())=="1"); break; }
                    }
                }
            } catch (...) {}
        }
        if (enabled_) worker_=std::thread([this]{ Write(); });
    }
    Csv(const Csv&)=delete;
    Csv& operator=(const Csv&)=delete;
    ~Csv() { Stop(); }
    bool Enabled() const { return enabled_; }
    std::uint64_t Tick() { return tick_.fetch_add(1, std::memory_order_relaxed)+1; }
    std::uint64_t LatestTick() const { return tick_.load(std::memory_order_relaxed); }
    void Record(Kind kind, std::uint64_t frame, std::uint64_t secondary,
                std::int64_t display_xr, std::int64_t pose_xr=0, std::int64_t aux=0) {
        if (!enabled_) return;
        const auto i=count_.fetch_add(1,std::memory_order_relaxed);
        if (i>=kLimit) return;  // 65k * multiple events; no allocation/overwrite
        auto& r=rows_[i];
        r.kind=kind;
        r.frame=frame;
        r.secondary=secondary;
        r.tick=LatestTick();
        r.qpc_ns=NowNs();
        r.display_xr=display_xr;
        r.pose_xr=pose_xr;
        r.aux=aux;
        r.ready.store(true,std::memory_order_release);
    }
    void Stop() {
        if (!enabled_) return;
        stopping_.store(true,std::memory_order_release);
        if (worker_.joinable()) worker_.join();
    }
};
#if defined(RESEARCH21_UEVR)
inline Csv& Sink() { static Csv s{"UEVR_WORLD_TRACE21"}; return s; }
#else
inline Csv& Sink() { static Csv s{"VECTORXR_FRAMEGEN_RESEARCH21"}; return s; }
#endif
} // namespace research_trace21
