// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include "common/settings_enums.h"

namespace Core {

[[nodiscard]] constexpr bool NeedsSystemReinitialization(bool has_device_memory,
                                                         bool initialized_multicore,
                                                         Settings::MemoryLayout initialized_layout,
                                                         bool requested_multicore,
                                                         Settings::MemoryLayout requested_layout) {
    return !has_device_memory || initialized_multicore != requested_multicore ||
           initialized_layout != requested_layout;
}

} // namespace Core
