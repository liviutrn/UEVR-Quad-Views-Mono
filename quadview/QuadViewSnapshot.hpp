#pragma once
// Tri-view B11 proof snapshots (shared by the compositor and the menu).
#include <atomic>
#include <cstdint>
#include <filesystem>
#include <mutex>
#include <string>

namespace uevr::quadview::dx12 {
// B11 proof snapshots: one request copies the final double-wide eye image, the
// three source renders and the periphery depth of the NEXT composite into
// CPU readback buffers; after that GPU slot retires, a background thread writes
// them as .dds files (+ an info .txt) into snapshot_directory().
inline std::atomic<bool>& snapshot_requested() { static std::atomic<bool> requested{false}; return requested; }
inline std::atomic<uint32_t>& snapshots_written() { static std::atomic<uint32_t> written{0}; return written; }
inline std::mutex& snapshot_mutex() { static std::mutex m; return m; }
inline std::filesystem::path& snapshot_directory_storage() { static std::filesystem::path dir; return dir; }
inline void set_snapshot_directory(const std::filesystem::path& dir) { std::scoped_lock l(snapshot_mutex()); snapshot_directory_storage() = dir; }
inline std::filesystem::path snapshot_directory() { std::scoped_lock l(snapshot_mutex()); return snapshot_directory_storage(); }
inline std::string& last_snapshot_message_storage() { static std::string m{"none yet"}; return m; }
inline std::string last_snapshot_message() { std::scoped_lock l(snapshot_mutex()); return last_snapshot_message_storage(); }

// B11: what the last composite did with periphery depth (menu/log proof):
// 0 not requested, 1 warping with depth, 2 depth bound but eye geometry invalid,
// 3 requested but no depth copy available, 4 depth bound for show only.
inline std::atomic<uint32_t>& last_depth_state() { static std::atomic<uint32_t> state{0}; return state; }
inline const char* depth_state_name(uint32_t s) {
    static const char* names[]{"not requested", "warping", "depth bound but eye geometry invalid", "no depth copy", "show only"};
    return s < 5 ? names[s] : "?";
}
} // namespace uevr::quadview::dx12
