// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#include <functional>
#include <utility>
#include <vector>

#include <catch2/catch_test_macros.hpp>

#include "common/common_types.h"
#include "core/gpu_dirty_memory_manager.h"

namespace {

using Ranges = std::vector<std::pair<PAddr, size_t>>;

Ranges Gathered(Core::GPUDirtyMemoryManager& manager) {
    Ranges ranges;
    std::function<void(PAddr, size_t)> callback = [&ranges](PAddr address, size_t size) {
        ranges.emplace_back(address, size);
    };
    manager.Gather(callback);
    return ranges;
}

} // namespace

// The expected values come from the 64 byte blocks and the 2 KiB lines that one report covers.
TEST_CASE("GPUDirtyMemoryManager: reports", "[core]") {
    Core::GPUDirtyMemoryManager manager;

    SECTION("A small store gathers its 64 byte block") {
        manager.Collect(0x10010, 4);
        REQUIRE(Gathered(manager) == Ranges{{0x10000, 64}});
    }
    SECTION("Near stores on one line join") {
        manager.Collect(0x10000, 4);
        manager.Collect(0x10040, 4);
        REQUIRE(Gathered(manager) == Ranges{{0x10000, 128}});
    }
    SECTION("A store that crosses a line gathers both blocks") {
        manager.Collect(0x107FC, 8);
        REQUIRE(Gathered(manager) == Ranges{{0x107C0, 64}, {0x10800, 64}});
    }
    SECTION("A whole page gathers its two lines") {
        manager.Collect(0x10000, 4096);
        REQUIRE(Gathered(manager) == Ranges{{0x10000, 2048}, {0x10800, 2048}});
    }
    SECTION("A line sized write at an offset gathers both parts") {
        manager.Collect(0x10400, 2048);
        REQUIRE(Gathered(manager) == Ranges{{0x10400, 1024}, {0x10800, 1024}});
    }
    SECTION("An empty report gathers nothing") {
        manager.Collect(0x10000, 0);
        REQUIRE(Gathered(manager).empty());
    }
    SECTION("A second gather finds nothing") {
        manager.Collect(0x10000, 4);
        REQUIRE(Gathered(manager).size() == 1);
        REQUIRE(Gathered(manager).empty());
    }
}
