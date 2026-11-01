// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#include <algorithm>

#include <catch2/catch_test_macros.hpp>

#include "audio_core/sink/null_sink.h"
#include "core/core.h"

TEST_CASE("Null audio input returns the requested silence", "[audio_core]") {
    Core::System system;
    AudioCore::Sink::NullSink sink{""};
    auto* stream = sink.AcquireSinkStream(system, 2, "Null input", AudioCore::Sink::StreamType::In);

    const auto samples = stream->ReleaseBuffer(480);

    REQUIRE(samples.size() == 480);
    CHECK(std::ranges::all_of(samples, [](s16 sample) { return sample == 0; }));
}
