#pragma once
// VectorXR/UEVR #21, opt-in. Recent-history ring, lock-free atomic records.
// A background thread snapshots the newest records to a unique per-launch
// CSV every 20 seconds and on clean shutdown. Never used for rendering.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>

namespace research_trace21 {
constexpr std::size_t kLimit=131072; // allocated ONLY with trace enabled
enum Kind : std::uint32_t { kGameTick=1,kRender=2,kPose=3,kSubmit=4,kXrWait=5,kXrRealEnd=6,kXrRefresh=7 };
struct Row {
    std::atomic<std::uint64_t> seq{0};
    std::atomic<std::uint64_t> frame{0},secondary{0},tick{0};
    std::atomic<std::int64_t> qpc_ns{0},display_xr{0},pose_xr{0},aux{0},extra{0};
    std::atomic<std::uint32_t> kind{0};
};
class Csv {
    std::unique_ptr<Row[]> rows_;
    std::atomic<std::uint64_t> cursor_{0}, tick_{0};
    std::atomic<bool> stop_{false};
    std::thread writer_;
    std::mutex snapshot_mutex_; // Serialize periodic and explicit session-end snapshots.
    bool enabled_{false};
    std::filesystem::path path_;

    static std::int64_t NowNs() {
        return std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count();
    }
    static std::string Key(const char* name) {
        if (const char* e=std::getenv(name)) return e;
        try {
            const char* local=std::getenv("LOCALAPPDATA");
            if (!local) return {};
            std::ifstream cfg(std::filesystem::path(local)/"VectorXR"/"framegen-research.txt");
            std::string s;
            const auto prefix=std::string(name)+"=";
            while (std::getline(cfg,s)) {
                if (!s.empty() && s.back()=='\r') s.pop_back();
                if (s.rfind(prefix,0)==0) return s.substr(prefix.size());
            }
        } catch (...) {}
        return {};
    }
    static std::string Mode() {
        const auto lock=Key("VECTORXR_CADENCE_LOCK21");
        if (lock=="5" || lock=="6") return "D";
        if (Key("VECTORXR_CONTENT_CLOCK21")=="1") return "B";
        if (Key("VECTORXR_MAX6_HYSTERESIS21")=="1") return "C";
        return "A";
    }
    static std::string Stamp() {
        const auto now=std::chrono::system_clock::now();
        const auto epoch=std::chrono::system_clock::to_time_t(now);
        std::tm local{};
#ifdef _WIN32
        localtime_s(&local,&epoch);
#else
        localtime_r(&epoch,&local);
#endif
        std::ostringstream os;
        os<<std::put_time(&local,"%Y%m%d-%H%M%S")<<'-'
          <<std::setfill('0')<<std::setw(6)
          <<(std::chrono::duration_cast<std::chrono::microseconds>(now.time_since_epoch()).count()%1000000);
        return os.str();
    }
    void Snapshot() noexcept {
        std::lock_guard<std::mutex> guard(snapshot_mutex_);
        if (!rows_ || path_.empty()) return;
        try {
            const auto partial=path_.string()+".partial";
            std::ofstream out(partial,std::ios::trunc);
            if (!out) return;
            out<<"kind,frame,secondary,tick,qpc_ns,display_xr,pose_xr,aux,extra\n";
            const auto end=cursor_.load(std::memory_order_acquire);
            const auto start=end>kLimit?end-kLimit:0;
            for(std::uint64_t i=start;i<end;++i) {
                const Row& r=rows_[i%kLimit];
                const auto before=r.seq.load(std::memory_order_acquire);
                if (before!=i+1) continue;
                const auto kind=r.kind.load(std::memory_order_relaxed);
                const auto frame=r.frame.load(std::memory_order_relaxed);
                const auto secondary=r.secondary.load(std::memory_order_relaxed);
                const auto tick=r.tick.load(std::memory_order_relaxed);
                const auto qpc=r.qpc_ns.load(std::memory_order_relaxed);
                const auto display=r.display_xr.load(std::memory_order_relaxed);
                const auto pose=r.pose_xr.load(std::memory_order_relaxed);
                const auto aux=r.aux.load(std::memory_order_relaxed);
                const auto extra=r.extra.load(std::memory_order_relaxed);
                // Keep the payload reads before the second seqlock validation.
                std::atomic_thread_fence(std::memory_order_acquire);
                if (r.seq.load(std::memory_order_acquire)!=before) continue;
                out<<kind<<','<<frame<<','<<secondary<<','<<tick<<','
                   <<qpc<<','<<display<<','<<pose<<','<<aux<<','<<extra<<'\n';
            }
            out.flush();
            out.close();
            if (!out) return;
            std::error_code error;
            std::filesystem::remove(path_,error);
            error.clear();
            std::filesystem::rename(partial,path_,error);
        } catch (...) {}
    }
    void Run() {
        unsigned secs=0;
        while(!stop_.load(std::memory_order_acquire)) {
            std::this_thread::sleep_for(std::chrono::seconds(1));
            if (++secs%20==0) Snapshot();
        }
        Snapshot();
    }
public:
    explicit Csv(const char* flag) {
        enabled_=Key(flag)=="1";
        if (!enabled_) return;
        try {
            const char* local=std::getenv("LOCALAPPDATA");
            if (!local) {enabled_=false; return;}
            const auto dir=std::filesystem::path(local)/"VectorXR";
            std::filesystem::create_directories(dir);
#if defined(RESEARCH21_UEVR)
            const auto prefix="uevr-world-trace21-";
#else
            const auto prefix="vectorxr-real-trace21-";
#endif
            path_=dir/(std::string(prefix)+Stamp()+"-"+Mode()+".csv");
            rows_=std::make_unique<Row[]>(kLimit);
            writer_=std::thread([this]{Run();});
        } catch (...) { enabled_=false; rows_.reset(); }
    }
    Csv(const Csv&)=delete; Csv& operator=(const Csv&)=delete;
    ~Csv(){Stop();}
    bool Enabled() const {return enabled_;}
    // Final recording point on OpenXR session teardown, not process exit.
    // Writer continues afterward; runtime reinit can still be traced.
    void FlushNow() noexcept { if (enabled_) Snapshot(); }
    std::uint64_t Tick(){return enabled_?tick_.fetch_add(1,std::memory_order_relaxed)+1:0;}
    std::uint64_t LatestTick() const{return tick_.load(std::memory_order_relaxed);}
    void Record(Kind kind,std::uint64_t frame,std::uint64_t secondary,
                std::int64_t display_xr,std::int64_t pose_xr=0,std::int64_t aux=0,
                std::int64_t extra=0) {
        if (!enabled_ || stop_.load(std::memory_order_relaxed)) return;
        const auto index=cursor_.fetch_add(1,std::memory_order_acq_rel);
        Row& r=rows_[index%kLimit];
        r.seq.store(0,std::memory_order_release);
        r.kind.store(static_cast<std::uint32_t>(kind),std::memory_order_relaxed);
        r.frame.store(frame,std::memory_order_relaxed);
        r.secondary.store(secondary,std::memory_order_relaxed);
        r.tick.store(LatestTick(),std::memory_order_relaxed);
        r.qpc_ns.store(NowNs(),std::memory_order_relaxed);
        r.display_xr.store(display_xr,std::memory_order_relaxed);
        r.pose_xr.store(pose_xr,std::memory_order_relaxed);
        r.aux.store(aux,std::memory_order_relaxed);
        r.extra.store(extra,std::memory_order_relaxed);
        r.seq.store(index+1,std::memory_order_release);
    }
    void Stop(){
        if (!enabled_ || stop_.exchange(true,std::memory_order_acq_rel)) return;
        if(writer_.joinable()) writer_.join();
    }
};
#if defined(RESEARCH21_UEVR)
inline Csv& Sink(){static Csv sink("UEVR_WORLD_TRACE21");return sink;}
#else
inline Csv& Sink(){static Csv sink("VECTORXR_FRAMEGEN_RESEARCH21");return sink;}
#endif
}
