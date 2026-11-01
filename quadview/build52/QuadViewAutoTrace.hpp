#pragma once
// Build52 diagnostic only. Standalone, bounded, crash-survivable evidence.
// This file is intentionally independent of the compositor and GPU readback.
// It is invoked from the already-gated per-stage HookTrace emitter.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <Windows.h>
#include <algorithm>
#include <cstdio>
#include <mutex>
#include <string>

namespace uevr::quadview::diagnostics {
inline std::wstring trace_path() {
    wchar_t temp[MAX_PATH]{};
    const DWORD count=GetTempPathW(MAX_PATH,temp);
    if (!count || count>=MAX_PATH) return {};
    return std::wstring(temp)+L"UEVR_Build52_Trace_"+std::to_wstring(GetCurrentProcessId())+L".csv";
}
inline std::string safe_field(const char* data) {
    std::string result;
    if (!data) return result;
    result.reserve(80);
    for (size_t i=0;data[i] && i<80;++i) {
        const unsigned char c=static_cast<unsigned char>(data[i]);
        result.push_back(c==' ' || c==',' || c=='"' || c=='\n' || c=='\r' || c=='\t' ? '_' :
                         c>=33 && c<127 ? static_cast<char>(c) : '_');
    }
    return result;
}
inline void persist_hook_event(size_t site,const HookTraceRecord& r,uint64_t count) {
    if (r.mode!=7) return; // Keep all non-QuadViews modes untouched.
    static std::mutex mutex;
    std::unique_lock<std::mutex> lock(mutex,std::try_to_lock);
    if (!lock.owns_lock()) return; // Diagnostics must never block the renderer.
    static unsigned written=0;
    if (written>=1600) return; // Strict disk and CPU cost bound.
    const auto path=trace_path();
    if (path.empty()) return;
    FILE* f=nullptr;
    if (_wfopen_s(&f,path.c_str(),L"ab")!=0 || !f) return;
    if (written==0) {
        std::fputs("tick_ms,site,count,event,reason,detail,generation,serial,frame,canonical_frame,"
                   "role,mode,result,rendered_mask,hooked_mask,executed_mask,written_mask,"
                   "source,native,engine,family,target,scene,root,tail,pending\n",f);
    }
    std::fprintf(f,
        "%llu,%zu,%llu,%s,%s,%s,%llu,%llu,%u,%u,%u,%d,%d,%u,%u,%u,%u,"
        "%d,%d,%d,%llx,%llx,%llx,%llx,%llx,%zu\n",
        static_cast<unsigned long long>(GetTickCount64()),site,static_cast<unsigned long long>(count),
        safe_field(r.event).c_str(),safe_field(r.reason).c_str(),safe_field(r.detail).c_str(),
        static_cast<unsigned long long>(r.generation),static_cast<unsigned long long>(r.serial),
        r.frame,r.canonical_frame,r.role,r.mode,r.result,r.rendered,r.hooked,r.executed,r.written,
        int(r.source),int(r.native),int(r.engine),
        static_cast<unsigned long long>(r.family),
        static_cast<unsigned long long>(r.target),
        static_cast<unsigned long long>(r.scene),
        static_cast<unsigned long long>(r.root),
        static_cast<unsigned long long>(r.tail),r.pending);
    std::fclose(f); // Explicit close: evidence survives crashes and early exits.
    ++written;
}
inline std::string read_persisted_hook_events() {
    const auto path=trace_path();
    if (path.empty()) return {};
    FILE* f=nullptr;
    if (_wfopen_s(&f,path.c_str(),L"rb")!=0 || !f) return {};
    std::string data;
    char buffer[4096];
    while (data.size()<512*1024) {
        const size_t n=std::fread(buffer,1,(std::min)(size_t(sizeof(buffer)),
                                 size_t(512*1024)-data.size()),f);
        if (!n) break;
        data.append(buffer,n);
    }
    std::fclose(f);
    return data;
}
} // namespace uevr::quadview::diagnostics
