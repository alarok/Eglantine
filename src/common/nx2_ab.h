// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include <chrono>
#include <cstdlib>
#include <string_view>

#include "common/common_types.h"

// EDEN_NX2_AB=<seconds> with EDEN_NX2_AB_ITEM=<name> compares one optimization inside one run. It
// is off for <seconds>, then on for <seconds>, and so on. Both sides then see the same scenes and
// the same load from other programs, so a small difference can be measured on a busy PC. The
// present thread logs the frame time of each side (nx2_gsv.h).
namespace Common::Nx2Ab {

inline const u32 g_seconds = [] {
    const char* value = std::getenv("EDEN_NX2_AB");
    return value != nullptr ? static_cast<u32>(std::strtoul(value, nullptr, 10)) : 0U;
}();

inline const std::string_view g_item = [] {
    const char* value = std::getenv("EDEN_NX2_AB_ITEM");
    return value != nullptr ? std::string_view{value} : std::string_view{};
}();

[[nodiscard]] inline bool Enabled() {
    return g_seconds != 0;
}

/// The side of the comparison at this moment.
[[nodiscard]] inline bool UseB() {
    const auto now = std::chrono::steady_clock::now().time_since_epoch();
    const auto seconds = std::chrono::duration_cast<std::chrono::seconds>(now).count();
    return (seconds / g_seconds) % 2 != 0;
}

/// Whether the optimization `item` is on. It is always on unless it is the one under comparison.
[[nodiscard]] inline bool On(std::string_view item) {
    return g_seconds == 0 || item != g_item || UseB();
}

} // namespace Common::Nx2Ab
