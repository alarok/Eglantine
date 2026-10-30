# Local controller API

Set `EGLANTINE_CONTROL_API=1` before starting the Qt GUI.
The API stays disabled when that value is absent or different.
API mode logs missing decryption keys instead of opening the startup notice.
Encrypted formats still require the correct keys.
The key installation menu retains its normal checks and dialogs.
Each process listens on an OS-selected TCP port at IPv4 address `127.0.0.1`.
The startup log records its port and process ID.
The API does not require a configuration file or a fixed port.
Loopback binding prevents connections from other machines.
It does not provide a Windows user access restriction.
Keep this opt-in interface disabled when it is not needed.

One client owns the virtual controller connection.
Requests and replies use one JSON object per line, encoded as UTF-8.
This protocol is not HTTP and has no CORS or HTTP action endpoints.
Malformed JSON closes the connection and discards remaining request bytes.
Keep pending requests below 8192 bytes.
Read each reply before sending the next request.
An unread reply queue over 65536 bytes closes the connection.
Commands execute on the GUI thread.
The API uses the existing virtual gamepad for player zero.
It does not change physical controller bindings or guest memory.

Examples:

```json
{"op":"status"}
{"op":"input","buttons":["DOWN"],"duration_ms":100}
{"op":"input","buttons":["A","B"],"left":[0.5,-1],"right":[0,0],"duration_ms":200}
{"op":"neutral"}
```

Input requests replace the complete virtual state.
Omitted buttons and sticks become neutral.
Renewing the same state extends its duration without releasing held buttons or resetting held sticks.
Backend callbacks receive only changed buttons or sticks during renewal.
Updates to different controls use separate backend calls; the API does not promise one atomic controller update.
Stick coordinates must be finite numbers between -1 and 1.
The duration must be an integer from 1 through 5000 milliseconds; its default is 100.
Only player zero is supported.
Buttons are A, B, X, Y, LSTICK, RSTICK, L, R, ZL, ZR, PLUS, MINUS, LEFT, UP, RIGHT, DOWN, SL, SR, HOME, CAPTURE.
Button names ignore case.

Expiration, client disconnection, pause, game change, stop, and application closure clear virtual input.
Starting, stopping, or changing the program also disconnects the client and discards pending requests.
Reconnect after each lifecycle change.
An invalid JSON command does not replace or extend a previous input state.
Malformed JSON closes the connection and therefore clears input.
Oversized input closes the connection and therefore clears input.
`applied=true` means the host virtual gamepad received the state.
It does not prove that the game acted on that state.

`status` includes API identity, process ID, TCP port, program ID, running state, paused state, and virtual input.
The API identity is `eglantine-controller-api-v1`.
FPS and frame time reuse the GUI's latest performance sample.
Frame time uses milliseconds; sample age also uses milliseconds.
Missing or stale performance data returns null.
The API does not reset performance counters.

The reusable PowerShell client discovers loopback listeners owned by the selected process.
Automatic discovery requires exactly one listener.
Supply `-Port` from the startup log when the process has several listeners.
The client checks API identity, process ID, and port before sending the requested command.
This check identifies the expected server; it is not authentication.

```powershell
.\tools\nx2\controller_client.ps1 -ProcessId 12345
.\tools\nx2\controller_client.ps1 -ProcessId 12345 -Port 54321
.\tools\nx2\controller_client.ps1 -ProcessId 12345 -Command '{"op":"input","buttons":["DOWN"],"duration_ms":100}'
```

The client stays connected until an acknowledged input pulse finishes.
Use `-DisconnectAfterReply` to test immediate release on disconnection.
Use `-KeepAliveMs` to choose a longer connection lifetime.
Disconnection releases input immediately, even when the requested duration has not expired.
A persistent client can send several requests through the same connection.

Behavior checks for a running test game:

1. Send DOWN for 100 milliseconds while another application has focus.
2. Confirm the selected menu entry changes in a captured game frame.
3. Send a stick state for 5000 milliseconds, then disconnect immediately.
4. Reconnect and confirm both sticks and all buttons are neutral.
5. Send A for 100 milliseconds, then B for 1000 milliseconds before A expires.
6. Confirm the old expiration does not release B.
7. Send an unknown button, player 10, a malformed stick, and a duration outside the allowed range.
8. Confirm each request fails without changing the previous state.
9. Stop or change the game during a held input and confirm the next game starts neutral.
10. Hold A. Renew A before expiration. Inspect the actual backend callback stream. Expect one initial press and one final release.
11. Queue a partial input request. Change the game. Confirm the old connection closes before its request can reach the new game.
12. Connect to a different listener. Confirm the identity check fails before any input is sent.
13. Send an HTTP request line followed by a JSON input command. Confirm the connection closes without applying input.

These checks require a live frontend and controller callbacks.
No source-scanning or mocked-controller tests substitute for those results.

## Recorded local check

The Windows integration build at `2da792dc2462a91490b7a638fcdc8ae4c1919f95` passed live host protocol checks.
Its SHA-256 is `b74a65441ce70f53b3cbd91495bd86c04c38a0af49e15ec09ffa8ab8b745e545`.
The checks covered renewal, invalid requests, expiration, disconnect release, malformed streams, and oversized requests.
A DOWN request lasting 400 milliseconds moved the Mario Kart World menu highlight from entry one to entry three.
That duration triggered key repeat. The test used the virtual gamepad without keyboard input.
Native game captures show the changed highlight under `docs/images/controller-api`.
The integration build also contains renderer candidates; this result establishes basic menu control.
Text labels remain missing in that isolated profile. Upstream PR #56 is already included in the tested source.

The native capture interval is 120 presents.
Require a newer captured frame before comparing an input result.
Short-pulse comparisons that reuse a frame are inconclusive.
Pause cleanup, program-change cleanup, and the complete backend callback sequence remain unverified.
Gameplay and a performance comparison remain unverified.
