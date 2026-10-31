// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include <array>
#include <QByteArray>
#include <QElapsedTimer>
#include <QJsonObject>
#include <QObject>
#include <QPointer>
#include <QTcpServer>
#include <QTimer>
#include "common/common_types.h"

namespace Core {
class System;
}
namespace InputCommon {
class InputSubsystem;
class VirtualGamepad;
} // namespace InputCommon
class QTcpSocket;

class ControllerApi final : public QObject {
public:
    ControllerApi(Core::System& system, InputCommon::InputSubsystem& input, QObject* parent);
    ~ControllerApi() override;

    void SetGameActive(bool active);
    void SetPerformanceSample(double fps, double frame_time_ms);
    void Neutralize();
    void Stop();

private:
    void AcceptConnection();
    void DisconnectClient();
    void RejectClient(const QString& message);
    bool UpdateProgram();
    void ReadCommands();
    QJsonObject Execute(const QJsonObject& command);
    QJsonObject Status() const;
    void Reply(QTcpSocket& client, const QJsonObject& reply);
    bool IsRunning() const;

    Core::System& system;
    InputCommon::VirtualGamepad* gamepad;
    QTcpServer server;
    QPointer<QTcpSocket> client;
    QByteArray pending;
    QTimer expiry;
    QTimer lifecycle;
    QMetaObject::Connection expiry_connection;
    u64 action_generation{};
    u64 program_id{};
    bool game_active{};
    bool stopped{};
    bool input_active{};
    std::array<bool, 20> buttons{};
    std::array<float, 2> left{};
    std::array<float, 2> right{};
    double fps{};
    double frame_time_ms{};
    QElapsedTimer sample_age;
};
