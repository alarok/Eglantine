// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#include <chrono>
#include <condition_variable>
#include <mutex>

#include <catch2/catch_test_macros.hpp>

#include "audio_core/audio_manager.h"
#include "core/hle/result.h"

TEST_CASE("Audio events raised during a callback are delivered promptly", "[audio_core]") {
    using namespace std::chrono_literals;
    std::mutex mutex;
    std::condition_variable changed;
    unsigned int calls = 0;
    bool release_first = false;
    AudioCore::AudioManager manager;
    const auto registered = manager.SetOutManager([&] {
        std::unique_lock lock{mutex};
        ++calls;
        changed.notify_all();
        if (calls == 1) {
            changed.wait(lock, [&] { return release_first; });
        }
    });

    std::unique_lock lock{mutex};
    const bool first = changed.wait_for(lock, 5s, [&] { return calls >= 1; });
    if (first) {
        manager.SetEvent(AudioCore::Event::Type::AudioOutManager, true);
    }
    release_first = true;
    changed.notify_all();
    const bool second = first && changed.wait_for(lock, 1s, [&] { return calls >= 2; });
    lock.unlock();
    manager.Shutdown();

    REQUIRE(registered.IsSuccess());
    REQUIRE(first);
    CHECK(second);
}
