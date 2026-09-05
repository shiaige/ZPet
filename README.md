# zpet

A desktop pet for ZCode. A small transparent window lives in the corner of your
screen and acts out what the AI is doing in real time — typing, pacing, resting
its chin in thought. It stops and flags you when approval is needed, and jumps
to celebrate when a task finishes.

Inspired by the Codex desktop pet and fully compatible with its pet format:
pets from the Codex / Petdex ecosystem (`pet.json` + spritesheet) work out of
the box when dropped into `~/.zcode/pets/`.

<!-- TODO: add a 10-second GIF here showing the pet switching between working / waiting / done -->

> Windows 10 / 11 only.

## Install

1. ZCode → Settings → Plugins → Marketplace → `+`, paste this repo's URL
2. Install zpet and restart ZCode. The pet shows up when your first session starts.

The repo ships a prebuilt daemon (~160MB, Qt embedded), so there is no Python
to install and no other runtime dependencies.

## How it behaves

ZCode's 7 hook events (prompt submitted, tool calls before/after, permission
requests, tool failures, session end) are sent over UDP to a local daemon,
which aggregates them into pet behavior:

- Four base states: working / needs input / blocked / done. With multiple
  sessions running, the highest priority wins: needs input > blocked > done >
  working. The bubble shows the session name.
- While working, it never loops the same animation forever: every 6–12 seconds
  it switches between typing, thinking, and pacing (pacing actually moves it
  30–90px).
- A state animation plays 3 rounds, then it settles into slow idle (frame
  duration ×6, randomly picking from the idle / float / look rows) until the
  aggregated state changes.
- On completion it jumps up to celebrate; after 90 seconds of being ignored it
  goes back to autonomous mode.

Interaction: drag it around (the running animation follows the drag direction,
it snaps to screen edges, and the position is remembered), it occasionally
hops when hovered, and a single click focuses the ZCode window. With the
system "reduce motion" setting on, it shows a static frame.

Extras, togglable from the right-click menu:

- Four autonomy levels (off / mild / lively / hyper): stretching, strolling,
  and waving when left alone
- Resident mode (on by default): the pet stays on the desktop after ZCode
  closes; turn it off to have it follow the last session's exit
- Fake typing: it types along when you type (only key timestamps are
  recorded, never the content)
- The bubble follows the pet; new assets dropped into `~/.zcode/pets/` take
  effect immediately via right-click → "Reload pet"

## Structure & how it works

```
├── .zcode-plugin\plugin.json   plugin manifest
├── marketplace.json            marketplace manifest (this repo is the marketplace)
├── hooks\hooks.json            7 hook events → ${ZCODE_PLUGIN_ROOT}\bin\zpet.exe
├── bin\zpet.exe                sender written in Rust (~220KB, GUI subsystem, no
│                               console flash): forwards the stdin payload; relaunches
│                               the daemon when it's down (so any hook event
│                               resurrects the pet)
├── bin\zpetd\                  daemon bundled with PyInstaller (PySide6 + PIL)
├── sender\                     Rust source of zpet.exe
├── daemon\zpet.py              daemon source (rendering / state machine / interaction / lifecycle)
├── daemon\zpet_send.py         manual sender for debugging
└── pets\xiaotian-pet\          bundled pet (v2 spec, 8×11 frames)
```

- Communication: `127.0.0.1:57891/UDP`, message format `<state>\x1F<hook
  payload JSON>`; the daemon holds the port exclusively.
- Process liveness is checked with in-process Win32 Toolhelp32 snapshots — no
  child processes, no window flashing, no UI stalls.
- Cold start is ~0.6s (PyInstaller trimmed: QML/Quick and unused Qt modules
  and plugin directories excluded).

## Custom pets

Pets are searched in two places: the plugin's `pets\` folder and your own
`~/.zcode/pets/`. The format follows Codex: `pet.json` +
`spritesheet.webp|.png`, an 8-column spritesheet with 192×208 frames and 9 or
11 rows, in the order idle / walk-right / walk-left / waving / jumping /
failed / waiting / working / review (v2 adds float / look). Frames per row
are auto-detected from trailing transparent cells. Pets from Petdex can be
dropped straight into `~/.zcode/pets/`.

## Building from source

For maintainers only — users just install the plugin.

```bash
# 1. Rust launcher (requires Rust toolchain)
cd sender && cargo build --release && cp target/release/zpet.exe ../bin/

# 2. Daemon (requires Python 3.11+, pip install PySide6 Pillow pyinstaller)
python -m PyInstaller --noconfirm --noconsole --onedir --name zpetd \
  --exclude-module PySide6.QtSql --exclude-module PySide6.QtSvg \
  --exclude-module PySide6.QtTest --exclude-module PySide6.QtXml \
  --exclude-module PySide6.QtPrintSupport --exclude-module PySide6.QtConcurrent \
  --exclude-module PySide6.QtOpenGL --exclude-module PySide6.QtQml \
  --exclude-module PySide6.QtQuick --exclude-module PySide6.QtMultimedia \
  daemon/zpet.py
for d in imageformats iconengines translations network; do
  rm -rf "dist/zpetd/_internal/Qt6/plugins/$d"; done
mv dist/zpetd bin/zpetd && rm -rf build dist zpetd.spec
```

Debugging: `ZPET_DEBUG=1 python daemon\zpet.py` (console logs + skips process
scanning); send a state manually: `echo {} | bin\zpet.exe send working`.

## License

MIT, see [LICENSE](LICENSE). The distributed binaries bundle third-party
libraries including PySide6 (LGPL-3.0) and Pillow; their licenses apply.
