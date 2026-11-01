// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#include <chrono>
#include <filesystem>
#include <memory>
#include <ostream>
#include <stdexcept>
#include <vector>

#include <catch2/catch_test_macros.hpp>

#include "common/fs/path_util.h"
#include "common/scope_exit.h"
#include "common/settings.h"
#include "core/core.h"
#include "core/device_memory.h"
#include "video_core/engines/maxwell_3d.h"
#include "video_core/host1x/gpu_device_memory_manager.h"
#include "video_core/memory_manager.h"
#include "video_core/rasterizer_interface.h"

namespace {
using Maxwell = Tegra::Engines::Maxwell3D;

struct Draw {
    u32 first;
    u32 count;
    u32 base_instance;
    u32 instances;
    bool indexed;

    bool operator==(const Draw&) const = default;
};

std::ostream& operator<<(std::ostream& output, const Draw& draw) {
    return output << "{first=" << draw.first << ", count=" << draw.count
                  << ", base=" << draw.base_instance << ", instances=" << draw.instances
                  << ", indexed=" << draw.indexed << '}';
}

class DrawRecorder final : public VideoCore::RasterizerInterface {
public:
    explicit DrawRecorder(Maxwell& engine_) : engine{engine_} {}

    void Draw(bool indexed, u32 instances) override {
        const auto& state = engine.draw_manager.draw_state;
        draws.push_back({state.vertex_buffer.first, state.vertex_buffer.count, state.base_instance,
                         instances, indexed});
    }
    void DrawTexture() override {}
    void Clear(u32) override {}
    void DispatchCompute() override {}
    void ResetCounter(VideoCommon::QueryType) override {}
    void Query(GPUVAddr, VideoCommon::QueryType, VideoCommon::QueryPropertiesFlags, u32,
               u32) override {}
    void BindGraphicsUniformBuffer(size_t, u32, GPUVAddr, u32) override {}
    void DisableGraphicsUniformBuffer(size_t, u32) override {}
    void SignalFence(std::function<void()>&&) override {}
    void SyncOperation(std::function<void()>&&) override {}
    void SignalSyncPoint(u32) override {}
    void SignalReference() override {}
    void ReleaseFences(bool) override {}
    void FlushAll() override {}
    void FlushRegion(DAddr, u64, VideoCommon::CacheType) override {}
    bool MustFlushRegion(DAddr, u64, VideoCommon::CacheType) override {
        return false;
    }
    VideoCore::RasterizerDownloadArea GetFlushArea(DAddr, u64) override {
        return {};
    }
    void InvalidateRegion(DAddr, u64, VideoCommon::CacheType) override {}
    void OnCacheInvalidation(PAddr, u64) override {}
    bool OnCPUWrite(PAddr, u64) override {
        return false;
    }
    void InvalidateGPUCache() override {}
    void UnmapMemory(DAddr, u64) override {}
    void ModifyGPUMemory(size_t, GPUVAddr, u64) override {}
    void FlushAndInvalidateRegion(DAddr, u64, VideoCommon::CacheType) override {}
    void WaitForIdle() override {}
    void FragmentBarrier() override {}
    void TiledCacheBarrier() override {}
    void FlushCommands() override {}
    void TickFrame() override {}
    Tegra::Engines::AccelerateDMAInterface& AccessAccelerateDMA() override {
        throw std::logic_error{"Unexpected DMA in packed draw test"};
    }
    void AccelerateInlineToMemory(GPUVAddr, size_t, std::span<const u8>) override {}

    std::vector<struct Draw> draws;

private:
    Maxwell& engine;
};
} // namespace

TEST_CASE("Packed array draws emit once and retain their instance sequence",
          "[video_core][packed_draw]") {
    const auto old_nand = Common::FS::GetEdenPath(Common::FS::EdenPath::NANDDir);
    const auto test_nand =
        std::filesystem::temp_directory_path() /
        ("eglantine-packed-draw-" +
         std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    REQUIRE(std::filesystem::create_directory(test_nand));
    SCOPE_EXIT {
        Common::FS::SetEdenPath(Common::FS::EdenPath::NANDDir, old_nand);
        std::filesystem::remove_all(test_nand);
    };
    Common::FS::SetEdenPath(Common::FS::EdenPath::NANDDir, test_nand);
    const auto old_layout = Settings::values.memory_layout_mode.GetValue();
    SCOPE_EXIT {
        Settings::values.memory_layout_mode.SetValue(old_layout);
    };
    Settings::values.memory_layout_mode.SetValue(Settings::MemoryLayout::Memory_4Gb);
    Core::DeviceMemory backing;
    Core::System system;
    Tegra::MaxwellDeviceMemoryManager device_memory{backing};
    Tegra::MemoryManager memory{system, device_memory, 32, 1ULL << 31};
    auto engine = std::make_unique<Maxwell>(memory);
    DrawRecorder recorder{*engine};
    engine->BindRasterizer(&recorder);
    auto& manager = engine->draw_manager;
    constexpr auto Triangles = Maxwell::Regs::PrimitiveTopology::Triangles;
    engine->regs.vertex_buffer = {101, 12};

    // NVIDIA clb197.h defines 0x1214 and 0x1218 as complete begin/end array draws.
    manager.DrawArrayInstanced(*engine, Triangles, 7, 3, false);
    SECTION("a later state boundary cannot repeat a completed draw") {
        manager.DrawDeferred(*engine);
        REQUIRE(recorder.draws == std::vector<Draw>{{7, 3, 0, 1, false}});
    }
    SECTION("subsequent draws keep their own vertex ranges") {
        manager.DrawArrayInstanced(*engine, Triangles, 19, 6, true);
        manager.DrawArrayInstanced(*engine, Triangles, 31, 9, true);
        manager.DrawDeferred(*engine);
        REQUIRE(recorder.draws ==
                std::vector<Draw>{{7, 3, 0, 1, false}, {19, 6, 1, 1, false}, {31, 9, 2, 1, false}});
    }
    SECTION("a state boundary preserves the next instance number") {
        manager.DrawDeferred(*engine);
        manager.DrawArrayInstanced(*engine, Triangles, 19, 6, true);
        manager.DrawDeferred(*engine);
        REQUIRE(recorder.draws == std::vector<Draw>{{7, 3, 0, 1, false}, {19, 6, 1, 1, false}});
    }
}
