// PSVR2 AutoRecover: SteamVR tracking monitor and non-destructive PSVR2 SLAM map recovery.
// Windows 10/11, x64. Uses only the OpenVR client API and documented/community-source
// PSVR2Toolkit.UnitySetup shared-memory command protocol. Never clears the SLAM map.
// See README.md for safety limits and attribution.
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <openvr.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>

using Clock = std::chrono::steady_clock;
using namespace std::chrono_literals;
namespace fs = std::filesystem;

namespace {
constexpr size_t kSharedSize = 0x2000000; // 32 MiB, Sony driver mapping
constexpr size_t kEvfFlagOffset = 0x110C200;
constexpr size_t kKeepAliveOffset = 0x9DD1;
constexpr size_t kSonyStatusOffset = 0x9AF0;
constexpr uint64_t kRefineMap = 0x2;
constexpr uint64_t kActivateMap = 0x4;
// 0x20 clears the SLAM map. Intentionally not present in recovery actions.
constexpr auto kPollInterval = 500ms;
constexpr auto kKeepAliveInterval = 1000ms;
constexpr auto kRefineTimeout = 12s;
constexpr auto kActivateTimeout = 15s;
constexpr auto kCooldown = 120s;
constexpr auto kHealthyConfirm = 3s;
constexpr auto kVrReconnectPeriod = 90s;

std::atomic_bool gRunning{true};
std::mutex gLogMutex;

BOOL WINAPI OnConsoleSignal(DWORD type) {
    if (type == CTRL_C_EVENT || type == CTRL_BREAK_EVENT || type == CTRL_CLOSE_EVENT ||
        type == CTRL_LOGOFF_EVENT || type == CTRL_SHUTDOWN_EVENT) {
        gRunning.store(false);
        return TRUE;
    }
    return FALSE;
}

std::string Timestamp() {
    SYSTEMTIME utc{};
    GetLocalTime(&utc);
    char s[40];
    std::snprintf(s, sizeof(s), "%04u-%02u-%02u %02u:%02u:%02u.%03u",
        utc.wYear, utc.wMonth, utc.wDay, utc.wHour, utc.wMinute,
        utc.wSecond, utc.wMilliseconds);
    return s;
}

fs::path LogPath() {
    char env[32768] = {};
    const DWORD len = GetEnvironmentVariableA("LOCALAPPDATA", env, sizeof(env));
    fs::path dir = (len && len < sizeof(env)) ? fs::path(env) : fs::current_path();
    dir /= "PSVR2AutoRecover";
    std::error_code ec;
    fs::create_directories(dir, ec);
    return dir / "recovery.log";
}

void Log(const std::string &message) {
    const std::string line = Timestamp() + " | " + message;
    std::lock_guard<std::mutex> lock(gLogMutex);
    std::cout << line << std::endl;
    std::ofstream out(LogPath(), std::ios::app);
    if (out) out << line << '\n';
}

class DriverInterface {
public:
    ~DriverInterface() { Close(); }

    bool Open() {
        if (pView_) return true;
        Close();
        // OpenExisting rather than Create: never fabricate an empty shared memory map.
        hMapping_ = OpenFileMappingA(FILE_MAP_READ | FILE_MAP_WRITE, FALSE, "SHARE_VRT2_WIN");
        if (!hMapping_) return false;
        pView_ = static_cast<uint8_t *>(MapViewOfFile(hMapping_,
            FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, kSharedSize));
        if (!pView_) { Close(); return false; }

        hEvfMutex_ = OpenMutexA(SYNCHRONIZE | MUTEX_MODIFY_STATE, FALSE,
            "SHARE_VRT2_WIN_EVF_MTX");
        hEvfEvent_ = OpenEventA(EVENT_MODIFY_STATE, FALSE, "SHARE_VRT2_WIN_EVF_EVT");
        hCommonMutex_ = OpenMutexA(SYNCHRONIZE | MUTEX_MODIFY_STATE, FALSE,
            "SHARE_VRT2_WIN_COMMON_MTX");
        hCommonEvent_ = OpenEventA(EVENT_MODIFY_STATE, FALSE,
            "SHARE_VRT2_WIN_COMMON_EVT");
        hStatusMutex_ = OpenMutexA(SYNCHRONIZE | MUTEX_MODIFY_STATE, FALSE,
            "SHARE_VRT2_WIN_VR_DIALOG_MTX");
        if (!hEvfMutex_ || !hEvfEvent_) { Close(); return false; }
        return true;
    }

    void Close() {
        if (pView_) { UnmapViewOfFile(pView_); pView_ = nullptr; }
        CloseHandleSafe(hStatusMutex_);
        CloseHandleSafe(hCommonEvent_);
        CloseHandleSafe(hCommonMutex_);
        CloseHandleSafe(hEvfEvent_);
        CloseHandleSafe(hEvfMutex_);
        CloseHandleSafe(hMapping_);
    }

    bool Ready() const { return pView_ != nullptr; }
    bool SignalCommand(uint64_t flag) {
        if (!Ready() || !hEvfMutex_ || !hEvfEvent_) return false;
        DWORD result = WaitForSingleObject(hEvfMutex_, 750);
        if (result != WAIT_OBJECT_0 && result != WAIT_ABANDONED) return false;
        // Exactly the same EVF flag slot and event as UnitySetup's TriggerEVFWorker.
        std::memcpy(pView_ + kEvfFlagOffset, &flag, sizeof(flag));
        const bool signaled = SetEvent(hEvfEvent_) != FALSE;
        ReleaseMutex(hEvfMutex_);
        return signaled;
    }

    bool KeepAlive() {
        if (!Ready() || !hCommonMutex_ || !hCommonEvent_) return false;
        DWORD result = WaitForSingleObject(hCommonMutex_, 300);
        if (result != WAIT_OBJECT_0 && result != WAIT_ABANDONED) return false;
        // UnitySetup increments this counter while its camera view is active.
        pView_[kKeepAliveOffset] = static_cast<uint8_t>(pView_[kKeepAliveOffset] + 1);
        const bool signaled = SetEvent(hCommonEvent_) != FALSE;
        ReleaseMutex(hCommonMutex_);
        return signaled;
    }

    int KeepAliveCounter() const {
        if (!Ready() || !hCommonMutex_) return -1;
        const DWORD wait = WaitForSingleObject(hCommonMutex_, 50);
        if (wait != WAIT_OBJECT_0 && wait != WAIT_ABANDONED) return -1;
        const int val = static_cast<int>(pView_[kKeepAliveOffset]);
        ReleaseMutex(hCommonMutex_);
        return val;
    }

    int SonyTrackingStatus() const {
        if (!Ready() || !hStatusMutex_) return -1;
        DWORD result = WaitForSingleObject(hStatusMutex_, 100);
        if (result != WAIT_OBJECT_0 && result != WAIT_ABANDONED) return -1;
        int32_t status = -1;
        std::memcpy(&status, pView_ + kSonyStatusOffset, sizeof(status));
        ReleaseMutex(hStatusMutex_);
        return status;
    }

private:
    static void CloseHandleSafe(HANDLE &handle) {
        if (handle) { CloseHandle(handle); handle = nullptr; }
    }
    HANDLE hMapping_ = nullptr;
    HANDLE hEvfMutex_ = nullptr;
    HANDLE hEvfEvent_ = nullptr;
    HANDLE hCommonMutex_ = nullptr;
    HANDLE hCommonEvent_ = nullptr;
    HANDLE hStatusMutex_ = nullptr;
    uint8_t *pView_ = nullptr;
};

enum class TrackingKind { Good, RotationOnly, Degraded, Unavailable };
struct TrackingSample {
    int result = -1;
    bool valid = false;
    bool connected = false;
    TrackingKind kind = TrackingKind::Unavailable;
    float x = 0, y = 0, z = 0;
};

TrackingKind Classify(int result, bool valid, bool connected) {
    if (!connected || result == 1 || result < 0) return TrackingKind::Unavailable;
    if (result == 300 && valid) return TrackingKind::RotationOnly;
    if (result == 200 && valid) return TrackingKind::Good;
    if (result == 201 || result == 100 || result == 101) return TrackingKind::Degraded;
    return TrackingKind::Unavailable;
}

std::string KindName(TrackingKind k) {
    switch (k) {
    case TrackingKind::Good: return "6DOF/Running_OK (as reported by SteamVR)";
    case TrackingKind::RotationOnly: return "RotationOnly/3DOF fallback";
    case TrackingKind::Degraded: return "Tracking out-of-range/calibrating";
    default: return "Unavailable/unknown";
    }
}

class OpenVrMonitor {
public:
    ~OpenVrMonitor() { Disconnect(); }
    bool EnsureConnected() {
        if (system_) return true;
        vr::EVRInitError error = vr::VRInitError_None;
        system_ = vr::VR_Init(&error, vr::VRApplication_Background);
        if (error != vr::VRInitError_None || !system_) {
            system_ = nullptr;
            return false;
        }
        Log("Connected to SteamVR OpenVR client (background mode).");
        return true;
    }
    TrackingSample Sample() {
        TrackingSample s;
        if (!system_) return s;
        vr::TrackedDevicePose_t poses[1]{};
        system_->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseRawAndUncalibrated,
            0.0f, poses, 1);
        s.result = static_cast<int>(poses[0].eTrackingResult);
        s.valid = poses[0].bPoseIsValid;
        s.connected = poses[0].bDeviceIsConnected;
        s.x = poses[0].mDeviceToAbsoluteTracking.m[0][3];
        s.y = poses[0].mDeviceToAbsoluteTracking.m[1][3];
        s.z = poses[0].mDeviceToAbsoluteTracking.m[2][3];
        s.kind = Classify(s.result, s.valid, s.connected);
        return s;
    }
    bool QuitRequested() {
        if (!system_) return false;
        vr::VREvent_t event{};
        while (system_->PollNextEvent(&event, sizeof(event))) {
            if (event.eventType == vr::VREvent_Quit ||
                event.eventType == vr::VREvent_DriverRequestedQuit ||
                event.eventType == vr::VREvent_RestartRequested) return true;
        }
        return false;
    }
    void Disconnect() {
        if (system_) {
            vr::VR_Shutdown();
            system_ = nullptr;
        }
    }
private:
    vr::IVRSystem *system_ = nullptr;
};

enum class Phase { Idle, Refine, Activate, Cooldown };

const char *PhaseName(Phase p) {
    switch(p) {
    case Phase::Idle: return "idle";
    case Phase::Refine: return "refine";
    case Phase::Activate: return "activate";
    case Phase::Cooldown: return "cooldown";
    }
    return "unknown";
}

// Deterministic predicates used by the production state machine and offline tests.
bool StableSixDof(TrackingKind kind, Clock::time_point since, Clock::time_point now) {
    return kind == TrackingKind::Good && since != Clock::time_point{} &&
           now - since >= kHealthyConfirm;
}
bool ShouldRefine(TrackingKind kind, bool previouslyStable, Clock::time_point since,
                  Clock::time_point now) {
    return kind == TrackingKind::RotationOnly && since != Clock::time_point{} &&
           now - since >= (previouslyStable ? 4s : 10s);
}

bool SelfTest() {
    bool pass = true;
    auto test = [&](bool check, const char *name) {
        std::cout << (check ? "PASS" : "FAIL") << " " << name << '\n';
        pass &= check;
    };
    test(Classify(200, true, true) == TrackingKind::Good, "running good");
    test(Classify(300, true, true) == TrackingKind::RotationOnly, "rotation fallback");
    test(Classify(201, true, true) == TrackingKind::Degraded, "out-of-range");
    test(Classify(200, false, true) != TrackingKind::Good, "invalid pose not OK");
    test(Classify(300, true, false) == TrackingKind::Unavailable, "disconnected HMD excluded");
    test(Classify(300, false, true) != TrackingKind::RotationOnly, "invalid fallback pose excluded");
    test(Classify(1, false, true) == TrackingKind::Unavailable, "uninitialized excluded");
    test(kRefineMap != 0x20 && kActivateMap != 0x20, "no clear-map recovery command");
    const auto t = Clock::now();
    test(!ShouldRefine(TrackingKind::RotationOnly, true, t, t + 3500ms), "no early refine");
    test(ShouldRefine(TrackingKind::RotationOnly, true, t, t + 4s), "refine on sustained 3DOF");
    test(!ShouldRefine(TrackingKind::RotationOnly, false, t, t + 9s), "startup 10s grace");
    test(ShouldRefine(TrackingKind::RotationOnly, false, t, t + 10s), "startup sustained 3DOF");
    test(!ShouldRefine(TrackingKind::Degraded, true, t, t + 120s), "do not auto-refine generic tracking errors");
    test(!ShouldRefine(TrackingKind::Unavailable, true, t, t + 120s), "do not auto-refine unavailable HMD");
    test(!StableSixDof(TrackingKind::Good, t, t + 2s), "no premature recovery confirmation");
    test(StableSixDof(TrackingKind::Good, t, t + 3s), "confirmed stable 6DOF");
    test(!StableSixDof(TrackingKind::RotationOnly, t, t + 20s), "3DOF cannot confirm success");
    return pass;
}

void Usage() {
    std::cout << "PSVR2 AutoRecover v0.2 (experimental, Windows x64)\n"
              << "  --watch         Monitor; refine sustained rotation-only tracking (default)\n"
              << "  --diagnostic    Observe and log tracking; NEVER send recovery commands\n"
              << "  --recover-once  Send one Refine Map command, then exit\n"
              << "  --auto-activate Opt-in second stage: Activate Map after Refine fails\n"
              << "  --self-test     Run offline classification/timing checks\n"
              << "  --help          Show this help\n\n"
              << "Logs: %LOCALAPPDATA%\\PSVR2AutoRecover\\recovery.log\n"
              << "No driver DLL or play area is replaced. Refine Map may update the Sony SLAM map.\n";
}

} // namespace

int main(int argc, char **argv) {
    bool diagnostic = false, recoverOnce = false, autoActivate = false;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--diagnostic") diagnostic = true;
        else if (arg == "--watch") diagnostic = false;
        else if (arg == "--recover-once") recoverOnce = true;
        else if (arg == "--auto-activate") autoActivate = true;
        else if (arg == "--self-test") return SelfTest() ? 0 : 1;
        else if (arg == "--help" || arg == "-h") { Usage(); return 0; }
        else { std::cerr << "Unknown option: " << arg << '\n'; Usage(); return 2; }
    }
    if ((diagnostic && (recoverOnce || autoActivate)) || (recoverOnce && autoActivate)) {
        std::cerr << "Conflicting flags: diagnostic mode cannot send commands.\n";
        return 2;
    }
    // An independent instance can overwrite the single EVF command slot.
    HANDLE oneInstance = CreateMutexA(nullptr, TRUE, "Local\\PSVR2AutoRecover-SingleInstance");
    if (!oneInstance) { std::cerr << "Could not create single-instance mutex.\n"; return 5; }
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
        std::cerr << "PSVR2 AutoRecover already running. Close it before starting another.\n";
        CloseHandle(oneInstance);
        return 5;
    }
    SetConsoleCtrlHandler(OnConsoleSignal, TRUE);
    Log(std::string("Starting v0.2. Mode: ") + (diagnostic ? "diagnostic" : (recoverOnce ? "refine-once" : "automatic")));
    Log("This utility NEVER clears the SLAM map and NEVER restarts SteamVR/UEVR.");
    Log(std::string("Auto Activate Map second stage: ") + (autoActivate ? "OPTED IN" : "OFF (default)"));
    DriverInterface driver;
    if (recoverOnce) {
        if (!driver.Open()) { Log("ERROR: PSVR2 Sony driver shared memory unavailable."); return 3; }
        const bool ok = driver.SignalCommand(kRefineMap);
        Log(ok ? "Manual Refine Map command signaled (not proof of recovery)." : "ERROR: Failed to signal Refine Map command.");
        return ok ? 0 : 4;
    }
    OpenVrMonitor openvr;
    TrackingKind oldKind = TrackingKind::Unavailable;
    int oldResult = -999;
    bool oldConnected = false;
    int oldSonyStatus = -999;
    Phase phase = Phase::Idle;
    Clock::time_point degradedSince{}, phaseSince{}, goodSince{}, lastKeepAlive{};
    Clock::time_point lastExternalSetup{}, unavailableSince{}, lastVrReconnect{};
    int previousKeepAliveCounter = -1;
    bool wasGood = false;
    bool loggedDriverUnavailable = false;
    auto lastConnectAttempt = Clock::now() - 20s;
    auto lastMappingAttempt = Clock::now() - 20s;
    auto lastHeartbeat = Clock::now();
    auto lastSonySample = Clock::now() - 20s;
    auto cooldownUntil = Clock::time_point{};

    while (gRunning.load()) {
        const auto now = Clock::now();
        if (openvr.QuitRequested()) {
            Log("SteamVR requested shutdown/restart: releasing OpenVR and Sony mapping handles.");
            openvr.Disconnect();
            driver.Close();
            phase = Phase::Idle;
            wasGood = false;
            degradedSince = goodSince = unavailableSince = Clock::time_point{};
            previousKeepAliveCounter = -1;
            lastConnectAttempt = lastMappingAttempt = now;
            std::this_thread::sleep_for(2s);
            continue;
        }
        if (now - lastConnectAttempt >= 5s) {
            lastConnectAttempt = now;
            openvr.EnsureConnected();
        }
        if (!driver.Ready() && now - lastMappingAttempt >= 5s) {
            lastMappingAttempt = now;
            if (driver.Open()) {
                Log("Connected to Sony PSVR2 driver shared memory.");
                loggedDriverUnavailable = false;
            } else if (!loggedDriverUnavailable) {
                Log("Sony driver mapping not found. Read-only monitor; recovery unavailable until driver connects.");
                loggedDriverUnavailable = true;
            }
        }
        const TrackingSample s = openvr.Sample();
        if (s.kind == TrackingKind::Unavailable) {
            if (unavailableSince == Clock::time_point{}) unavailableSince = now;
            if (now - unavailableSince >= 30s && now - lastVrReconnect >= kVrReconnectPeriod) {
                Log("OpenVR HMD unavailable: reopening runtime and Sony mapping handles.");
                lastVrReconnect = now;
                openvr.Disconnect();
                driver.Close();
                phase = Phase::Idle;
                wasGood = false;
                degradedSince = goodSince = Clock::time_point{};
                previousKeepAliveCounter = -1;
                lastConnectAttempt = lastMappingAttempt = now;
                std::this_thread::sleep_for(1s);
                continue;
            }
        } else {
            unavailableSince = Clock::time_point{};
        }
        const int currentKeepAliveCounter = driver.KeepAliveCounter();
        if (currentKeepAliveCounter >= 0) {
            if (previousKeepAliveCounter >= 0 && currentKeepAliveCounter != previousKeepAliveCounter &&
                phase != Phase::Refine && phase != Phase::Activate) {
                lastExternalSetup = now;
            }
            previousKeepAliveCounter = currentKeepAliveCounter;
        }
        const bool roomSetupActive = lastExternalSetup != Clock::time_point{} &&
                                     now - lastExternalSetup < 4s;
        int sonyStatus = -1;
        if (driver.Ready()) sonyStatus = driver.SonyTrackingStatus();
        if (s.kind != oldKind || s.result != oldResult || s.connected != oldConnected) {
            Log("HMD " + KindName(s.kind) + " (OpenVR tracking=" + std::to_string(s.result) +
                ", pose_valid=" + std::to_string(s.valid) + ", connected=" + std::to_string(s.connected) +
                ", Sony status=" + std::to_string(sonyStatus) + ", raw_position_m=" +
                std::to_string(s.x) + "," + std::to_string(s.y) + "," + std::to_string(s.z) + ")");
            oldKind = s.kind;
            oldResult = s.result;
            oldConnected = s.connected;
        }
        if (sonyStatus != oldSonyStatus && (now - lastSonySample >= 3s || oldSonyStatus == -999)) {
            Log("Sony tracking status changed: " + std::to_string(oldSonyStatus) + " -> " + std::to_string(sonyStatus) +
                " (meaning unverified; logged for comparison, not used to trigger recovery).");
            oldSonyStatus = sonyStatus;
            lastSonySample = now;
        }
        if (now - lastHeartbeat > 60s) {
            Log("Heartbeat: phase=" + std::string(PhaseName(phase)) +
                ", OpenVR=" + std::to_string(s.result) + ", Sony=" + std::to_string(sonyStatus) +
                ", raw_position_m=" + std::to_string(s.x) + "," + std::to_string(s.y) +
                "," + std::to_string(s.z));
            lastHeartbeat = now;
        }

        if (s.kind == TrackingKind::Good) {
            degradedSince = Clock::time_point{};
            if (goodSince == Clock::time_point{}) goodSince = now;
            if (StableSixDof(s.kind, goodSince, now)) wasGood = true;
            if ((phase == Phase::Refine || phase == Phase::Activate) && StableSixDof(s.kind, goodSince, now)) {
                Log("SteamVR reports Running_OK for >=3 seconds after recovery command; positional 6DOF still requires headset verification.");
                phase = Phase::Cooldown;
                cooldownUntil = now + 15s;
            }
        } else {
            goodSince = Clock::time_point{};
            if (s.kind == TrackingKind::RotationOnly) {
                if (degradedSince == Clock::time_point{}) degradedSince = now;
            } else {
                degradedSince = Clock::time_point{};
                if (s.kind == TrackingKind::Unavailable &&
                    (phase == Phase::Refine || phase == Phase::Activate)) {
                    Log("HMD unavailable during recovery; aborting commands and cooling down.");
                    phase = Phase::Cooldown;
                    cooldownUntil = now + kCooldown;
                }
            }
        }

        if (!diagnostic && driver.Ready()) {
            if (phase == Phase::Cooldown && now >= cooldownUntil) phase = Phase::Idle;
            if (phase == Phase::Idle && !roomSetupActive &&
                ShouldRefine(s.kind, wasGood, degradedSince, now)) {
                    if (driver.SignalCommand(kRefineMap)) {
                        Log("AUTO: signaled Refine Map command (0x2). Driver execution and 6DOF recovery unconfirmed.");
                        phase = Phase::Refine;
                        phaseSince = now;
                        lastKeepAlive = now - kKeepAliveInterval;
                    } else {
                        Log("ERROR: driver refused Refine Map command; entering cooldown.");
                        phase = Phase::Cooldown;
                        cooldownUntil = now + kCooldown;
                    }
            }
            if (phase == Phase::Refine || phase == Phase::Activate) {
                if (now - lastKeepAlive >= kKeepAliveInterval) {
                    if (!driver.KeepAlive()) Log("WARNING: PSVR2 setup-mode keepalive unavailable.");
                    lastKeepAlive = now;
                }
                if (phase == Phase::Refine && now - phaseSince >= kRefineTimeout) {
                    if (autoActivate && s.kind == TrackingKind::RotationOnly &&
                        driver.SignalCommand(kActivateMap)) {
                        Log("AUTO: Refine did not restore 6DOF; sent Activate Map command (0x4).");
                        phase = Phase::Activate;
                        phaseSince = now;
                    } else {
                        Log(autoActivate ? "AUTO: Activate Map was not appropriate or unavailable."
                                         : "AUTO: Refine stage expired without confirmed recovery."
                                           " Activate Map is disabled by default for safety.");
                        phase = Phase::Cooldown;
                        cooldownUntil = now + kCooldown;
                    }
                } else if (phase == Phase::Activate && now - phaseSince >= kActivateTimeout) {
                    Log("AUTO: No verified 6DOF recovery. Stopping attempts for 120 seconds. "
                        "Try PSVR2Toolkit.UnitySetup -> Refine Map manually, or improve camera visibility.");
                    phase = Phase::Cooldown;
                    cooldownUntil = now + kCooldown;
                }
            }
        }
        std::this_thread::sleep_for(kPollInterval);
    }
    Log("Stopped gracefully.");
    ReleaseMutex(oneInstance);
    CloseHandle(oneInstance);
    return 0;
}