#pragma once
#include <stdint.h>
#define UEVR_SOURCE_ROLES_VERSION 1u
enum UevrSourceRole : uint32_t {
    UEVR_ROLE_UNKNOWN = 0,
    UEVR_ROLE_DUO_FOVEA = 1,      // ID6 high-res gaze crop
    UEVR_ROLE_DUO_PERIPHERY = 2,  // ID6 low-res full FOV
    UEVR_ROLE_TRI_FOVEA_LEFT = 3, // ID7
    UEVR_ROLE_TRI_FOVEA_RIGHT = 4,
    UEVR_ROLE_TRI_PERIPHERY = 5,
};
struct UevrSourceRoleEntryV1 {
    uint64_t ngx_feature_handle;  // the NVSDK_NGX_Handle* value seen at EvaluateFeature
    uint32_t role;                // UevrSourceRole
    uint32_t out_width, out_height;
    uint32_t in_width, in_height; // DLSS render subrect
    uint32_t reserved;
};
struct UevrSourceRolesV1 {
    uint32_t struct_size;         // caller sets sizeof(UevrSourceRolesV1)
    uint32_t version;             // producer writes 1
    uint32_t rendering_method;    // 6 DuoView, 7 TriView, else 0
    uint32_t transition_in_progress; // 1 from layout change request until new sources have evaluated twice
    uint64_t layout_generation;   // increments on any layout/size/method change
    uint64_t produced_qpc_ns;     // steady_clock ns of the last update
    uint32_t count;               // valid entries
    uint32_t reserved;
    UevrSourceRoleEntryV1 entries[6];
};
// Exported from UEVRBackend.dll. Returns 0 if unavailable or if struct_size is too small.
extern "C" __declspec(dllexport) int __cdecl UEVR_GetSourceRolesV1(UevrSourceRolesV1* out);
