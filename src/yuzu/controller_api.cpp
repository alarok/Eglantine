// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#include <algorithm>
#include <cmath>
#include <QCoreApplication>
#include <QHostAddress>
#include <QJsonArray>
#include <QJsonDocument>
#include <QStringList>
#include <QTcpSocket>
#include "common/logging.h"
#include "core/core.h"
#include "input_common/drivers/virtual_gamepad.h"
#include "input_common/main.h"
#include "yuzu/controller_api.h"

namespace {
constexpr qsizetype MaxCommandBytes = 8192;
const QString ApiIdentity = QStringLiteral("eglantine-controller-api-v1");
const std::array<QString, 20> ButtonNames{
    QStringLiteral("A"),    QStringLiteral("B"),       QStringLiteral("X"),
    QStringLiteral("Y"),    QStringLiteral("LSTICK"),  QStringLiteral("RSTICK"),
    QStringLiteral("L"),    QStringLiteral("R"),       QStringLiteral("ZL"),
    QStringLiteral("ZR"),   QStringLiteral("PLUS"),    QStringLiteral("MINUS"),
    QStringLiteral("LEFT"), QStringLiteral("UP"),      QStringLiteral("RIGHT"),
    QStringLiteral("DOWN"), QStringLiteral("SL"),      QStringLiteral("SR"),
    QStringLiteral("HOME"), QStringLiteral("CAPTURE"),
};

QJsonObject Error(const QString& message) {
    return {{QStringLiteral("ok"), false}, {QStringLiteral("error"), message}};
}

bool ReadStick(const QJsonValue& value, std::array<float, 2>& stick) {
    if (value.isUndefined()) {
        return true;
    }
    if (!value.isArray() || value.toArray().size() != 2) {
        return false;
    }
    const auto coordinates = value.toArray();
    for (qsizetype i = 0; i < 2; ++i) {
        if (!coordinates[i].isDouble()) {
            return false;
        }
        const double coordinate = coordinates[i].toDouble();
        if (!std::isfinite(coordinate) || coordinate < -1.0 || coordinate > 1.0) {
            return false;
        }
        stick[i] = static_cast<float>(coordinate);
    }
    return true;
}
} // namespace

ControllerApi::ControllerApi(Core::System& system_, InputCommon::InputSubsystem& input,
                             QObject* parent)
    : QObject{parent}, system{system_}, gamepad{input.GetVirtualGamepad()} {
    connect(&server, &QTcpServer::newConnection, this, &ControllerApi::AcceptConnection);
    expiry.setSingleShot(true);
    lifecycle.setInterval(100);
    connect(&lifecycle, &QTimer::timeout, this, [this] {
        UpdateProgram();
        if (input_active && !IsRunning()) {
            Neutralize();
        }
    });
    connect(QCoreApplication::instance(), &QCoreApplication::aboutToQuit, this,
            &ControllerApi::Stop);
    if (gamepad == nullptr || !server.listen(QHostAddress{QHostAddress::LocalHost}, 0)) {
        LOG_ERROR(Frontend, "Local controller API could not listen: {}",
                  server.errorString().toStdString());
        return;
    }
    lifecycle.start();
    LOG_INFO(Frontend, "Local controller API {} listening on 127.0.0.1:{} for PID {}",
             ApiIdentity.toStdString(), server.serverPort(), QCoreApplication::applicationPid());
}

ControllerApi::~ControllerApi() {
    Stop();
}

void ControllerApi::Stop() {
    if (stopped) {
        return;
    }
    stopped = true;
    lifecycle.stop();
    server.close();
    DisconnectClient();
}

void ControllerApi::DisconnectClient() {
    Neutralize();
    if (client) {
        disconnect(client.data(), nullptr, this, nullptr);
        client->abort();
        client->deleteLater();
        client.clear();
    }
    pending.clear();
}

void ControllerApi::SetGameActive(bool active) {
    DisconnectClient();
    game_active = active;
    program_id = active && system.IsPoweredOn() ? system.GetApplicationProcessProgramID() : 0;
    sample_age.invalidate();
}

bool ControllerApi::UpdateProgram() {
    const auto current_program =
        game_active && system.IsPoweredOn() ? system.GetApplicationProcessProgramID() : 0;
    if (current_program == program_id) {
        return false;
    }
    DisconnectClient();
    program_id = current_program;
    sample_age.invalidate();
    return true;
}

bool ControllerApi::IsRunning() const {
    return !stopped && game_active && system.IsPoweredOn() && !system.IsShuttingDown() &&
           !system.IsPaused();
}

void ControllerApi::SetPerformanceSample(double fps_, double frame_time_ms_) {
    if (!std::isfinite(fps_) || !std::isfinite(frame_time_ms_) || fps_ < 0.0 ||
        frame_time_ms_ < 0.0) {
        sample_age.invalidate();
        return;
    }
    fps = fps_;
    frame_time_ms = frame_time_ms_;
    sample_age.start();
}

void ControllerApi::Neutralize() {
    ++action_generation;
    expiry.stop();
    disconnect(expiry_connection);
    if (gamepad != nullptr && input_active) {
        constexpr std::array<float, 2> centered{};
        for (std::size_t i = 0; i < buttons.size(); ++i) {
            if (buttons[i]) {
                gamepad->SetButtonState(0, static_cast<int>(i), false);
            }
        }
        if (left != centered) {
            gamepad->SetStickPosition(0, InputCommon::VirtualGamepad::VirtualStick::Left, 0.0f,
                                      0.0f);
        }
        if (right != centered) {
            gamepad->SetStickPosition(0, InputCommon::VirtualGamepad::VirtualStick::Right, 0.0f,
                                      0.0f);
        }
    }
    buttons.fill(false);
    left.fill(0.0f);
    right.fill(0.0f);
    input_active = false;
}

void ControllerApi::AcceptConnection() {
    if (stopped) {
        return;
    }
    while (server.hasPendingConnections()) {
        auto* incoming = server.nextPendingConnection();
        UpdateProgram();
        incoming->setReadBufferSize(MaxCommandBytes + 1);
        connect(incoming, &QTcpSocket::disconnected, incoming, &QObject::deleteLater);
        if (client) {
            Reply(*incoming, Error(QStringLiteral("Another client owns the controller")));
            incoming->disconnectFromHost();
            continue;
        }
        client = incoming;
        pending.clear();
        connect(incoming, &QTcpSocket::readyRead, this, &ControllerApi::ReadCommands);
        connect(incoming, &QTcpSocket::disconnected, this, [this, incoming] {
            if (client != incoming) {
                return;
            }
            Neutralize();
            pending.clear();
            client.clear();
        });
    }
}

void ControllerApi::Reply(QTcpSocket& destination, const QJsonObject& reply) {
    const auto data = QJsonDocument{reply}.toJson(QJsonDocument::Compact) + '\n';
    if (destination.bytesToWrite() + data.size() > 65536) {
        destination.abort();
        return;
    }
    destination.write(data);
}

void ControllerApi::RejectClient(const QString& message) {
    const auto rejected_client = client;
    Reply(*rejected_client, Error(message));
    if (rejected_client) {
        rejected_client->disconnectFromHost();
    }
    pending.clear();
    Neutralize();
}

void ControllerApi::ReadCommands() {
    if (stopped || !client || client->state() != QAbstractSocket::ConnectedState) {
        return;
    }
    pending += client->read(MaxCommandBytes + 1);
    for (auto newline = pending.indexOf('\n');
         client && client->state() == QAbstractSocket::ConnectedState && newline >= 0;
         newline = pending.indexOf('\n')) {
        if (newline > MaxCommandBytes) {
            RejectClient(QStringLiteral("Command exceeds 8192 bytes"));
            return;
        }
        const auto line = pending.left(newline);
        pending.remove(0, newline + 1);
        QJsonParseError parse_error;
        const auto document = QJsonDocument::fromJson(line, &parse_error);
        if (parse_error.error != QJsonParseError::NoError || !document.isObject()) {
            RejectClient(QStringLiteral("Expected one JSON object per line"));
            return;
        }
        const auto requesting_client = client;
        const auto reply = Execute(document.object());
        if (client && client == requesting_client) {
            Reply(*client, reply);
        }
    }
    if (client && client->state() == QAbstractSocket::ConnectedState &&
        pending.size() > MaxCommandBytes) {
        RejectClient(QStringLiteral("Command exceeds 8192 bytes"));
    }
}

QJsonObject ControllerApi::Status() const {
    QJsonArray pressed;
    for (std::size_t i = 0; i < buttons.size(); ++i) {
        if (buttons[i]) {
            pressed.append(ButtonNames[i]);
        }
    }
    const bool powered = game_active && system.IsPoweredOn();
    QJsonObject reply{
        {QStringLiteral("ok"), true},
        {QStringLiteral("api"), ApiIdentity},
        {QStringLiteral("pid"), QCoreApplication::applicationPid()},
        {QStringLiteral("port"), server.serverPort()},
        {QStringLiteral("running"), IsRunning()},
        {QStringLiteral("paused"), powered && system.IsPaused()},
        {QStringLiteral("program_id"),
         powered ? QJsonValue{QStringLiteral("%1").arg(system.GetApplicationProcessProgramID(), 16,
                                                       16, QLatin1Char{'0'})}
                 : QJsonValue{}},
        {QStringLiteral("player"), 0},
        {QStringLiteral("buttons"), pressed},
        {QStringLiteral("left"), QJsonArray{left[0], left[1]}},
        {QStringLiteral("right"), QJsonArray{right[0], right[1]}}};
    const bool fresh = IsRunning() && sample_age.isValid() && sample_age.elapsed() <= 5000;
    reply.insert(QStringLiteral("fps"), fresh ? QJsonValue{fps} : QJsonValue{});
    reply.insert(QStringLiteral("frame_time_ms"), fresh ? QJsonValue{frame_time_ms} : QJsonValue{});
    reply.insert(QStringLiteral("sample_age_ms"),
                 sample_age.isValid() ? QJsonValue{sample_age.elapsed()} : QJsonValue{});
    return reply;
}

QJsonObject ControllerApi::Execute(const QJsonObject& command) {
    if (UpdateProgram()) {
        return Error(QStringLiteral("The application changed; reconnect before sending commands"));
    }
    const auto operation = command.value(QStringLiteral("op")).toString();
    const QStringList allowed =
        operation == QLatin1String{"input"}
            ? QStringList{QStringLiteral("op"),      QStringLiteral("player"),
                          QStringLiteral("buttons"), QStringLiteral("left"),
                          QStringLiteral("right"),   QStringLiteral("duration_ms")}
            : QStringList{QStringLiteral("op")};
    for (auto it = command.begin(); it != command.end(); ++it) {
        if (!allowed.contains(it.key())) {
            return Error(QStringLiteral("Unknown request field: %1").arg(it.key()));
        }
    }
    if (operation == QLatin1String{"status"}) {
        return Status();
    }
    if (operation == QLatin1String{"neutral"}) {
        Neutralize();
        return {{QStringLiteral("ok"), true}, {QStringLiteral("applied"), true}};
    }
    if (operation != QLatin1String{"input"}) {
        return Error(QStringLiteral("Unknown operation"));
    }
    const auto player = command.value(QStringLiteral("player"));
    if (!player.isUndefined() && (!player.isDouble() || player.toDouble() != 0.0)) {
        return Error(QStringLiteral("Only player 0 is supported"));
    }
    const auto requested_buttons = command.value(QStringLiteral("buttons"));
    if (!requested_buttons.isUndefined() && !requested_buttons.isArray()) {
        return Error(QStringLiteral("buttons must be an array"));
    }
    std::array<bool, 20> next_buttons{};
    for (const auto& value : requested_buttons.toArray()) {
        const auto name = value.isString() ? value.toString().toUpper() : QString{};
        const auto found = std::find(ButtonNames.begin(), ButtonNames.end(), name);
        if (found == ButtonNames.end()) {
            return Error(QStringLiteral("Unknown controller button"));
        }
        next_buttons[static_cast<std::size_t>(found - ButtonNames.begin())] = true;
    }
    std::array<float, 2> next_left{}, next_right{};
    if (!ReadStick(command.value(QStringLiteral("left")), next_left) ||
        !ReadStick(command.value(QStringLiteral("right")), next_right)) {
        return Error(QStringLiteral("Each stick requires two finite numbers between -1 and 1"));
    }
    const auto duration_value = command.value(QStringLiteral("duration_ms"));
    const double duration = duration_value.isUndefined() ? 100.0 : duration_value.toDouble(-1.0);
    if ((!duration_value.isUndefined() && !duration_value.isDouble()) || !std::isfinite(duration) ||
        duration != std::floor(duration) || duration < 1.0 || duration > 5000.0) {
        return Error(QStringLiteral("duration_ms must be an integer between 1 and 5000"));
    }
    if (!IsRunning()) {
        return Error(QStringLiteral("No game is running or the game is paused"));
    }

    ++action_generation;
    expiry.stop();
    disconnect(expiry_connection);
    for (std::size_t i = 0; i < buttons.size(); ++i) {
        if (buttons[i] != next_buttons[i]) {
            gamepad->SetButtonState(0, static_cast<int>(i), next_buttons[i]);
        }
    }
    if (left != next_left) {
        gamepad->SetStickPosition(0, InputCommon::VirtualGamepad::VirtualStick::Left, next_left[0],
                                  next_left[1]);
    }
    if (right != next_right) {
        gamepad->SetStickPosition(0, InputCommon::VirtualGamepad::VirtualStick::Right,
                                  next_right[0], next_right[1]);
    }
    buttons = next_buttons;
    left = next_left;
    right = next_right;
    input_active = true;
    const auto generation = action_generation;
    expiry_connection = connect(&expiry, &QTimer::timeout, this, [this, generation] {
        if (generation == action_generation) {
            Neutralize();
        }
    });
    expiry.start(static_cast<int>(duration));
    return {{QStringLiteral("ok"), true},
            {QStringLiteral("applied"), true},
            {QStringLiteral("duration_ms"), duration}};
}
