// SPDX-FileCopyrightText: Copyright 2025 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

// SPDX-FileCopyrightText: Copyright 2022 yuzu Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include "audio_core/audio_event.h"
#include "common/assert.h"
#include "common/scope_exit.h"
#include <ranges>

namespace AudioCore {

size_t Event::GetManagerIndex(const Type type) const {
    switch (type) {
    case Type::AudioInManager:
        return 0;
    case Type::AudioOutManager:
        return 1;
    case Type::FinalOutputRecorderManager:
        return 2;
    case Type::Max:
        return 3;
    default:
        UNREACHABLE();
    }
}

void Event::SetAudioEvent(const Type type, const bool signalled) {
    {
        std::scoped_lock notification_lock{notification_mutex};
        events_signalled[GetManagerIndex(type)] = signalled;
    }
    if (signalled) {
        manager_event.notify_one();
    }
}

bool Event::CheckAudioEventSet(const Type type) const {
    return events_signalled[GetManagerIndex(type)];
}

bool Event::ConsumeAudioEvent(const Type type) {
    return events_signalled[GetManagerIndex(type)].exchange(false);
}

std::mutex& Event::GetAudioEventLock() {
    return event_lock;
}

std::condition_variable_any& Event::GetAudioEvent() {
    return manager_event;
}

bool Event::Wait(std::unique_lock<std::mutex>& l, const std::chrono::seconds timeout) {
    l.unlock();
    SCOPE_EXIT { l.lock(); };
    std::unique_lock notification_lock{notification_mutex};
    bool timed_out{false};
    if (!manager_event.wait_for(notification_lock, timeout, [&]() {
            return std::ranges::any_of(events_signalled, [](bool x) { return x; });
        })) {
        timed_out = true;
    }
    return timed_out;
}

void Event::ClearEvents() {
    events_signalled[0] = false;
    events_signalled[1] = false;
    events_signalled[2] = false;
    events_signalled[3] = false;
}

} // namespace AudioCore
