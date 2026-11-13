#pragma once
// Contract C2 v1 (DuoView/TriView source roles -> Cheeky). Copied verbatim by both sides.
#include <stdint.h>
#define UEVR_SOURCE_ROLES_VERSION 1u
enum UevrSourceRole : uint32_t {
    UEVR_ROLE_UNKNOWN = 0,
    UEVR_ROLE_DUO_FOVEA = 1,
    UEVR_ROLE_DUO_PERIPHERY = 2,
    UEVR_ROLE_TRI_FOVEA_LEFT = 3,
    UEVR_ROLE_TRI_FOVEA_RIGHT = 4,
    UEVR_ROLE_TRI_PERIPHERY = 5,
};
struct UevrSourceRoleEntryV1 {
    uint64_t ngx_feature_handle;
    uint32_t role;
    uint32_t out_width, out_height;
    uint32_t in_width, in_height;
    uint32_t reserved;
};
struct UevrSourceRolesV1 {
    uint32_t struct_size;
    uint32_t version;
    uint32_t rendering_method;
    uint32_t transition_in_progress;
    uint64_t layout_generation;
    uint64_t produced_qpc_ns;
    uint32_t count;
    uint32_t reserved;
    UevrSourceRoleEntryV1 entries[6];
};
