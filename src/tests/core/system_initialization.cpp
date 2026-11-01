// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#include <catch2/catch_test_macros.hpp>

#include "core/system_initialization.h"

using Core::NeedsSystemReinitialization;
using Settings::MemoryLayout;

TEST_CASE("System initialization requires backing memory", "[core][initialization]") {
    CHECK(NeedsSystemReinitialization(false, true, MemoryLayout::Memory_8Gb, true,
                                      MemoryLayout::Memory_8Gb));
}

TEST_CASE("System initialization retains matching settings", "[core][initialization]") {
    CHECK_FALSE(NeedsSystemReinitialization(true, true, MemoryLayout::Memory_8Gb, true,
                                            MemoryLayout::Memory_8Gb));
    CHECK_FALSE(NeedsSystemReinitialization(true, false, MemoryLayout::Memory_12Gb, false,
                                            MemoryLayout::Memory_12Gb));
}

TEST_CASE("System initialization distinguishes memory layouts", "[core][initialization]") {
    CHECK(NeedsSystemReinitialization(true, true, MemoryLayout::Memory_4Gb, true,
                                      MemoryLayout::Memory_12Gb));
    CHECK(NeedsSystemReinitialization(true, true, MemoryLayout::Memory_8Gb, true,
                                      MemoryLayout::Memory_12Gb));
    CHECK(NeedsSystemReinitialization(true, true, MemoryLayout::Memory_12Gb, true,
                                      MemoryLayout::Memory_8Gb));
    CHECK(NeedsSystemReinitialization(true, true, MemoryLayout::Memory_6Gb, true,
                                      MemoryLayout::Memory_10Gb));
}

TEST_CASE("System initialization distinguishes multicore settings", "[core][initialization]") {
    CHECK(NeedsSystemReinitialization(true, true, MemoryLayout::Memory_8Gb, false,
                                      MemoryLayout::Memory_8Gb));
    CHECK(NeedsSystemReinitialization(true, false, MemoryLayout::Memory_8Gb, true,
                                      MemoryLayout::Memory_8Gb));
}
