#include <cassert>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <type_traits>
#include <utility>
#include <vector>

namespace sdk {
struct UObjectBase {
    uint64_t identity_generation{1};
    bool alive{true};
};

namespace object_liveness {
struct Identity {
    UObjectBase* object{};
    uint64_t generation{};
};
struct Observation { Identity identity{}; };
}

struct UObject : UObjectBase {
    std::wstring full_name{};
    explicit UObject(std::wstring name = {}) : full_name(std::move(name)) {}
    std::wstring get_full_name() const { return full_name; }
};

struct UFunction { enum class Kind { getter, setter } kind{}; };
struct OwnedFName {
    std::wstring value{};
    explicit OwnedFName(std::wstring_view name) : value(name) {}
};
inline UFunction getter_function{UFunction::Kind::getter};
inline UFunction setter_function{UFunction::Kind::setter};
inline size_t class_lookups{};
inline size_t function_lookups{};
inline size_t object_scans{};
inline std::vector<std::pair<std::wstring, float>> writes{};

struct MaterialCollection : UObject {
    float enabled{1.0f};
    float depth{2.0f};
    explicit MaterialCollection(std::wstring name = L"World.MPC_FOV") : UObject(std::move(name)) {}
};

struct UClass : UObject {
    UObject* default_object{};
    explicit UClass(UObject* object) : UObject(L"Class /Script/Engine.KismetMaterialLibrary"), default_object(object) {}
    UObject* get_class_default_object() { return default_object; }
    UFunction* find_function(std::wstring_view name) {
        ++function_lookups;
        if (name == L"GetScalarParameterValue") return &getter_function;
        if (name == L"SetScalarParameterValue") return &setter_function;
        return nullptr;
    }
};

struct Engine { UObject* world{}; UObject* get_world() { return world; } };

inline std::optional<object_liveness::Observation> observe_uobject(UObjectBase* object) {
    if (!object) return {};
    return object_liveness::Observation{{object, object->identity_generation}};
}

inline bool is_current_object(const object_liveness::Identity& identity) {
    return identity.object && identity.object->alive &&
        identity.object->identity_generation == identity.generation;
}

inline UObject* class_default_object{};
template<class T> T* find_uobject(std::wstring_view) {
    ++class_lookups;
    return reinterpret_cast<T*>(class_default_object);
}

struct ReflectedNameCall {
    UFunction* function{};
    UObject* world{};
    MaterialCollection* collection{};
    std::wstring parameter{};
    float scalar{};
    bool has_return{};
    explicit ReflectedNameCall(UFunction* f) : function(f) {}

    template<class T> bool write(std::wstring_view field, T value) {
        if (field == L"WorldContextObject") {
            if constexpr (std::is_same_v<T, UObject*>) { world = value; return true; }
            return false;
        }
        if (field == L"Collection") {
            if constexpr (std::is_same_v<T, UObject*>) {
                collection = reinterpret_cast<MaterialCollection*>(value); return true;
            }
            return false;
        }
        if (field == L"ParameterValue") {
            if constexpr (std::is_same_v<T, float>) { scalar = value; return true; }
            return false;
        }
        return false;
    }
    bool write_name(std::wstring_view field, const std::wstring& value) {
        if (field != L"ParameterName") return false;
        parameter = value;
        return true;
    }
    bool write_name(std::wstring_view field, std::wstring_view value) {
        if (field != L"ParameterName") return false;
        parameter.assign(value);
        return true;
    }
    bool write_name(std::wstring_view field, const OwnedFName& value) {
        if (field != L"ParameterName") return false;
        parameter = value.value;
        return true;
    }
    bool field(std::wstring_view name, size_t size) {
        has_return = name == L"ReturnValue" && size == sizeof(float);
        return has_return;
    }
    bool invoke(UObject*) {
        if (!function || !world || !collection || parameter.empty()) return false;
        auto& value = parameter == L"IsFOVEnabled" ? collection->enabled : collection->depth;
        if (function->kind == UFunction::Kind::getter) {
            if (!has_return) return false;
            scalar = value;
            return true;
        }
        value = scalar;
        writes.emplace_back(parameter, scalar);
        return true;
    }
    template<class T> T read(std::wstring_view name) const {
        if constexpr (std::is_same_v<T, float>) return name == L"ReturnValue" && has_return ? scalar : 0.0f;
        return {};
    }
};
}

inline std::vector<sdk::UObject*> live_objects{};
inline std::vector<sdk::UObject*> get_live_objects_by_class_name(std::wstring_view) {
    ++sdk::object_scans;
    return live_objects;
}

struct Toggle { bool enabled{true}; bool value() const { return enabled; } };

#define SPDLOG_WARNING_EVERY_N_SEC(...) ((void)0)
#define SPDLOG_INFO(...) ((void)0)

class ForegroundMPCHarness {
public:
    sdk::Engine engine_storage{};
    sdk::Engine* engine{&engine_storage};
    sdk::UObject* world{};
    sdk::MaterialCollection* collection{};
    sdk::UObject library{L"Default__KismetMaterialLibrary"};
    sdk::UClass klass{&library};
    std::shared_ptr<Toggle> m_quadview_foreground_mpc{std::make_shared<Toggle>()};
    bool quadview_selected{true};
    bool supported_title{true};

    ForegroundMPCHarness(sdk::UObject* world_object, sdk::MaterialCollection* collection_object)
        : world(world_object), collection(collection_object) {
        engine_storage.world = world;
        sdk::class_default_object = &klass;
        live_objects = {collection};
    }

    bool is_quadview_mode_selected() const { return quadview_selected; }
    bool is_quadview_supported_title() const { return supported_title; }

    template<int Case> void tick() {
#include "foreground_mpc_runtime.inc"
    }
};

static void reset_observation_counts() {
    sdk::class_lookups = 0;
    sdk::function_lookups = 0;
    sdk::object_scans = 0;
    sdk::writes.clear();
}

static void test_conditional_writes_and_saved_restore() {
    sdk::UObject world{L"World"};
    sdk::MaterialCollection collection;
    ForegroundMPCHarness harness{&world, &collection};
    reset_observation_counts();

    harness.tick<1>();
    assert(collection.enabled == 0.0f && collection.depth == 1.0f);
    assert(sdk::writes.size() == 2);
    assert(sdk::object_scans == 1 && sdk::class_lookups == 1 && sdk::function_lookups == 2);

    harness.tick<1>();
    assert(sdk::writes.size() == 2); // Stable world values cause reads, never setter traffic.
    assert(sdk::object_scans == 1 && sdk::class_lookups == 1 && sdk::function_lookups == 2);

    collection.enabled = 1.0f; // Game drifted only IsFOVEnabled.
    harness.tick<1>();
    assert(collection.enabled == 0.0f && collection.depth == 1.0f);
    assert(sdk::writes.size() == 3 && sdk::writes.back().first == L"IsFOVEnabled");

    harness.m_quadview_foreground_mpc->enabled = false;
    harness.tick<1>();
    assert(collection.enabled == 1.0f && collection.depth == 2.0f);
    assert(sdk::writes.size() == 5);
    assert((sdk::writes[3] == std::pair<std::wstring, float>{L"IsFOVEnabled", 1.0f}));
    assert((sdk::writes[4] == std::pair<std::wstring, float>{L"DepthScale", 2.0f}));
    harness.tick<1>();
    assert(sdk::writes.size() == 5); // Deactivation is one-shot.
}

static void test_stale_collection_identity_refuses_writes() {
    sdk::UObject world{L"World.CollectionCase"};
    sdk::MaterialCollection collection;
    ForegroundMPCHarness harness{&world, &collection};
    reset_observation_counts();

    harness.tick<2>();
    assert(sdk::writes.size() == 2);
    const auto writes_before_stale = sdk::writes.size();
    collection.alive = false;
    ++collection.identity_generation;
    harness.tick<2>();
    assert(sdk::writes.size() == writes_before_stale);
    assert(collection.enabled == 0.0f && collection.depth == 1.0f);
}

static void test_stale_world_identity_refuses_writes() {
    sdk::UObject world{L"World.WorldCase"};
    sdk::MaterialCollection collection;
    ForegroundMPCHarness harness{&world, &collection};
    reset_observation_counts();

    harness.tick<3>();
    assert(sdk::writes.size() == 2);
    const auto writes_before_stale = sdk::writes.size();
    world.alive = false;
    ++world.identity_generation;
    harness.tick<3>();
    assert(sdk::writes.size() == writes_before_stale);
    assert(collection.enabled == 0.0f && collection.depth == 1.0f);
}

int main() {
    test_conditional_writes_and_saved_restore();
    test_stale_collection_identity_refuses_writes();
    test_stale_world_identity_refuses_writes();
}
