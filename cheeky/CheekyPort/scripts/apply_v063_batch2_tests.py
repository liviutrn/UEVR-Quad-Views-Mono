#!/usr/bin/env python3
"""Append deterministic Cheeky C2, allocation, and reuse tests after Batch2."""
from pathlib import Path
import sys

root=Path(sys.argv[1]).resolve()
test=root/"tests/uevr_tests.cpp"
text=test.read_text(encoding="utf-8")
def replace(before,after,name):
    global text
    n=text.count(before)
    if n!=1: raise SystemExit(f"Batch2 test {name}: anchor {n}, expected 1; no write")
    text=text.replace(before,after,1)
replace('#include "settings_io.hpp"',
        '''#include "settings_io.hpp"
#include "../src/uevr_source_roles_consumer_v1.hpp"
#include "../src/nr_batch2_policy.hpp"''',
        "host policy headers")
replace('int main(int argc, char** argv) {',
        r'''namespace {
UevrSourceRolesV1 fake_c2_roles_batch2{};
int __cdecl fake_c2_export_batch2(UevrSourceRolesV1* out) {
    if (!out || out->struct_size != sizeof(UevrSourceRolesV1)) return 0;
    *out=fake_c2_roles_batch2;
    return 1;
}
void test_cheeky_batch2_contract() {
    auto& s=fake_c2_roles_batch2;
    s={};s.struct_size=sizeof(s);
    s.version=UEVR_SOURCE_ROLES_VERSION;
    s.rendering_method=6;
    s.layout_generation=35;
    s.count=2;
    s.entries[0].ngx_feature_handle=0x1000;
    s.entries[0].role=UEVR_ROLE_DUO_FOVEA;
    s.entries[1].ngx_feature_handle=0x2000;
    s.entries[1].role=UEVR_ROLE_DUO_PERIPHERY;
    auto decision=c2_query_with_provider(&fake_c2_export_batch2,0x1000);
    require(decision.authoritative && decision.role_mask==1 && decision.method==6 &&
            decision.generation==35, "C2: authoritative Duo fovea");
    decision=c2_query_with_provider(&fake_c2_export_batch2,0x2000);
    require(decision.authoritative && decision.role_mask==4,"C2: Duo periphery");
    require(!c2_query_with_provider(nullptr,0x1000).authoritative,"C2: absent export falls back");
    require(!c2_query_with_provider(&fake_c2_export_batch2,0x3000).authoritative,
        "C2: unknown NGX handle falls back");
    s.version=2;
    require(!c2_query_with_provider(&fake_c2_export_batch2,0x1000).authoritative,
        "C2: mismatched version cannot reclassify");
    s.version=1;s.rendering_method=7;s.layout_generation=36;
    s.entries[0].role=UEVR_ROLE_TRI_FOVEA_RIGHT;
    s.entries[1].role=UEVR_ROLE_TRI_PERIPHERY;
    decision=c2_query_with_provider(&fake_c2_export_batch2,0x1000);
    require(decision.authoritative && decision.role_mask==2 && decision.method==7,
        "C2: Tri right maps to physical eye 2");
    decision=c2_query_with_provider(&fake_c2_export_batch2,0x2000);
    require(decision.authoritative && decision.role_mask==4,
        "C2: Tri periphery not confused with right fovea");
    s.transition_in_progress=1;s.count=0;
    decision=c2_query_with_provider(&fake_c2_export_batch2,0x1000);
    require(decision.authoritative && decision.transition && decision.role_mask==0,
        "C2: empty transition stops NR and will retire old family");
    s.transition_in_progress=0;
    require(!c2_query_with_provider(&fake_c2_export_batch2,0x1000).authoritative,
        "C2: empty stable snapshot falls back");

    constexpr std::uint64_t mib=nr_batch2_mib;
    require(nr_batch2_admit(true,2048*mib,512*mib,1536*mib),
        "Admission: exact free budget boundary");
    require(!nr_batch2_admit(true,2048*mib-1,512*mib,1536*mib),
        "Admission: guard cannot be borrowed");
    require(!nr_batch2_admit(false,3000*mib,512*mib,1536*mib),
        "Admission: invalid DXGI report fails closed");
    require(!nr_batch2_admit(true,100*mib,UINT64_MAX,2*mib),
        "Admission: underflow/overflow-safe comparison");
    require(nr_batch2_reuse_eligible(true,true,true,true,true,true,10000,0),
        "Reuse: exact 10s expiry and fence completion");
    require(!nr_batch2_reuse_eligible(true,true,true,true,true,false,1,0),
        "Reuse: no use before GPU completion");
    require(!nr_batch2_reuse_eligible(true,true,true,false,true,true,1,0),
        "Reuse: changed FeatureKey invalidates reuse");
    require(!nr_batch2_reuse_eligible(true,true,false,true,true,true,1,0),
        "Reuse: Duo/Tri family mismatch invalidates reuse");
    require(!nr_batch2_reuse_eligible(true,true,true,true,false,true,1,0),
        "Reuse: GPU device mismatch invalidates reuse");
    require(!nr_batch2_reuse_eligible(true,true,true,true,true,true,10001,0),
        "Reuse: >10s cannot reuse");
    require(!nr_batch2_reuse_eligible(false,true,true,true,true,true,1,0),
        "Reuse: opt-out never reuses");

    Settings user{};
    require(user.nr_use_source_roles && user.nr_alloc_admission && user.nr_feature_reuse,
        "Batch2: safety defaults ON when older INI lacks keys");
    require(set_named_setting(user,"NrUseSourceRoles","0") && !user.nr_use_source_roles,
        "Batch2: source-role flag persisted");
    require(set_named_setting(user,"NrAllocAdmission","0") && !user.nr_alloc_admission,
        "Batch2: allocation flag persisted");
    require(set_named_setting(user,"NrFeatureReuse","0") && !user.nr_feature_reuse,
        "Batch2: feature reuse flag persisted");
}
} // namespace

int main(int argc, char** argv) {''', "test fixtures")
replace('''        wchar_t exe[MAX_PATH]{}; GetModuleFileNameW(nullptr, exe, MAX_PATH);''',
        '''        test_cheeky_batch2_contract();
        wchar_t exe[MAX_PATH]{}; GetModuleFileNameW(nullptr, exe, MAX_PATH);''',
        "test executes before UEVR host setup")
test.write_text(text,encoding="utf-8",newline="\n")
print("PASS Batch2 C2 ABI mocks; DXGI budget and fence/reuse policy tests inserted")
