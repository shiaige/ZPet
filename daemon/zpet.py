#!/usr/bin/env pythonw
"""zpet daemon — official Codex pet behavior core plus optional extras.

Official core (from the Codex docs, the hatch-pet atlas contract, and the
decompiled app renderer):
  - 4 logical agent states: running / needs_input / blocked / ready
  - a state animation plays 3 loops, then falls back to idle until the
    aggregated state changes (the decompiled renderer slows that fallback
    idle ~6x; skipped here — a ~1fps pet reads as broken, see codex#28995)
  - multi-session aggregation priority: needs_input > blocked > ready > running
  - drag plays running-left/right by movement direction, with a grab cursor
  - system "reduced motion" renders a static first frame

Extras (right-click menu, default on): autonomous behavior (4 levels),
hover jump, keyboard busy reaction, resident mode (pet stays when ZCode
closes), hot pet reload, and a bubble that follows the pet.

Set ZPET_DEBUG=1 for a console log and to skip the process scan.
"""
import ctypes
import json
import os
import random
import re
import sys
import time

from PIL import Image
from PySide6 import QtCore, QtGui, QtWidgets, QtNetwork

PORT = int(os.environ.get("ZPET_PORT", "57891"))  # override keeps tests off the live pet
DEBUG = os.environ.get("ZPET_DEBUG") == "1"
if getattr(sys, "frozen", False):
    # PyInstaller onedir layout: <plugin>\bin\zpetd\zpetd.exe
    PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(sys.executable))))
else:
    PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_PETS_DIR = os.path.join(os.path.expanduser("~"), ".zcode", "pets")
STATE_FILE = os.path.join(USER_PETS_DIR, "zpet-state.json")
FRAME_W, FRAME_H = 192, 208

# Codex atlas contract: row and official LOOP duration (ms). Frame counts vary
# between community pets, so per-frame time = loop / actual frame count —
# every pet keeps the official tempo with smooth uniform motion. (A fixed
# per-frame rhythm table would only fit the reference pet.)
CLIPS = {
    "idle":          dict(row=0,  loop_ms=1100),
    "running-right": dict(row=1,  loop_ms=1060),
    "running-left":  dict(row=2,  loop_ms=1060),
    "waving":        dict(row=3,  loop_ms=700),
    "jumping":       dict(row=4,  loop_ms=840),
    "failed":        dict(row=5,  loop_ms=1220),
    "waiting":       dict(row=6,  loop_ms=1010),
    "running":       dict(row=7,  loop_ms=820),
    "review":        dict(row=8,  loop_ms=1030),
    "float":         dict(row=9,  loop_ms=1200),  # v2 extras, pets may lack them
    "look":          dict(row=10, loop_ms=1200),
}
STATE_LOOPS = 3           # official: a state animation plays 3 loops

# state -> animation pool. running rotates through its pool while working
# (community doc: working = typing/pondering/walking back and forth); ready
# celebrates (jump/wave). Directional picks trigger an actual short walk.
AGENT_STATE_CLIPS = {
    "needs_input": ["waiting"],
    "blocked": ["failed"],
    "ready": ["jumping", "waving"],
    "running": ["running", "review", "running-left", "running-right"],
    "thinking": ["review"],
}
# official aggregation priority, most urgent first (thinking is transient)
STATE_PRIORITY = ["needs_input", "blocked", "ready", "running", "thinking"]
# ZCode hook events -> logical state
EVENT_STATE = {"review": "thinking", "working": "running", "waiting": "needs_input",
               "failed": "blocked", "done": "ready"}
SESSION_STUCK_S = 600     # a session with no events for this long drops out
READY_EXPIRE_S = 90       # ready frees the pet back to autonomous life sooner
WORK_ROTATE_S = (6, 12)   # working-animation rotation interval

# autonomous behavior levels: gate seconds, per-action cooldowns, walk px, double-action chance
AUTONOMY_PRESETS = {
    "off":   None,
    "mild":  dict(gate=15, cds=(4, 5, 6, 9),    dist=(24, 60),  dbl=0.0),
    "lively": dict(gate=10, cds=(3.5, 4.5, 5, 7), dist=(30, 90), dbl=0.25),
    "hyper": dict(gate=5,  cds=(2.5, 3, 4, 6),  dist=(30, 120), dbl=0.4),
}
SCHEDULER_ACTIONS = [
    dict(key="attention_shift", clips=["review", "waiting", "idle", "float", "look"], weight=3, cd_idx=0),
    dict(key="short_move", clips=["running-left", "running-right"], weight=2, cd_idx=1),
    dict(key="greet_variant", clips=["waving", "idle"], weight=1, cd_idx=2),
    dict(key="calm_idle", clips=["waiting", "idle"], weight=1, cd_idx=3),
]
MOVE_SPEED = 18.0         # px/s
SNAP_PX = 24              # edge snap distance after a drag

HOVER_COOLDOWN_S = 2.0
KEYBOARD_BURST_S = 3.0
KEYBOARD_REROLL_S = 1.0
KEYBOARD_CLIPS = ["running", "review", "waiting", "float", "look"]

CLICK_MS = 180
PROC_SCAN_MS = 15000
PROC_GRACE_S = 20


def log(*a):
    if DEBUG:
        print(*a, file=sys.stderr)


def reduced_motion():
    """Windows 'reduce animations' -> official pets render a static frame."""
    try:
        v = ctypes.c_bool()
        ctypes.windll.user32.SystemParametersInfoW(
            0x1042, 0, ctypes.byref(v), 0)  # SPI_GETCLIENTAREAANIMATION
        return not v.value
    except Exception:
        return False


def clean_text(md, limit=120):
    t = re.sub(r"```.*?```", "[代码]", md, flags=re.S)
    t = re.sub(r"[*_`#>|]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[: limit - 1] + "…" if len(t) > limit else t


def session_label(payload):
    try:
        cwd = json.loads(payload).get("cwd") or ""
        return os.path.basename(cwd.rstrip("\\/")) if cwd else "ZCode"
    except Exception:
        return "ZCode"


def discover_pets():
    pets = []
    seen = set()
    for root in (os.path.join(PLUGIN_ROOT, "pets"), USER_PETS_DIR):
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            pj = os.path.join(d, "pet.json")
            if name not in seen and os.path.isfile(pj):
                seen.add(name)
                try:
                    meta = json.load(open(pj, encoding="utf-8"))
                except Exception:
                    continue
                pets.append({"name": name, "dir": d, "meta": meta})
    return pets


def sheet_path(pet):
    p = pet["meta"].get("spritesheetPath")
    if p and os.path.isfile(os.path.join(pet["dir"], p)):
        return os.path.join(pet["dir"], p)
    for f in ("spritesheet.webp", "spritesheet.png"):
        if os.path.isfile(os.path.join(pet["dir"], f)):
            return os.path.join(pet["dir"], f)
    return None


def load_frames(info):
    """row index -> [QPixmap, ...], detecting each row's real frame count by
    scanning for the fully-transparent trailing cells."""
    path = sheet_path(info)
    if not path:
        raise FileNotFoundError(f"no spritesheet for {info['name']}")
    img = Image.open(path).convert("RGBA")
    rows = {}
    for row in range(img.height // FRAME_H):
        y = row * FRAME_H
        frames = []
        for col in range(img.width // FRAME_W):
            cell = img.crop((col * FRAME_W, y, (col + 1) * FRAME_W, y + FRAME_H))
            if cell.getbbox() is None:
                break
            data = cell.tobytes("raw", "RGBA")
            qi = QtGui.QImage(data, FRAME_W, FRAME_H, FRAME_W * 4,
                              QtGui.QImage.Format_RGBA8888).copy()
            frames.append(QtGui.QPixmap.fromImage(qi))
        if frames:
            rows[row] = frames
    if 0 not in rows:
        raise ValueError(f"{info['name']}: no usable rows")
    return rows


class Pet:
    def __init__(self, info, zoom, rows=None):
        self.info = info
        self.meta = info["meta"]
        self.rows = rows if rows is not None else load_frames(info)
        self.set_zoom(zoom)

    @property
    def display_name(self):
        return self.meta.get("displayName", self.info["name"])

    def set_zoom(self, zoom):
        self.zoom = zoom
        self.size = (int(FRAME_W * zoom), int(FRAME_H * zoom))
        self.scaled = {
            row: [f.scaled(*self.size, QtCore.Qt.IgnoreAspectRatio,
                           QtCore.Qt.FastTransformation)
                  for f in frames]
            for row, frames in self.rows.items()
        }


class KeyboardMonitor:
    """WH_KEYBOARD_LL timestamp recorder — the callback only stores a float,
    nothing about the keystroke itself is kept."""

    def __init__(self):
        self.last_key_at = 0.0
        self._hook = None
        self._proc = None

    def install(self):
        user32 = ctypes.windll.user32
        self._proc = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p)(self._on_key)
        # NULL hMod is required here: python.exe's own module handle is rejected
        self._hook = user32.SetWindowsHookExW(13, self._proc, None, 0)
        log("keyboard hook:", bool(self._hook))

    def uninstall(self):
        if self._hook:
            ctypes.windll.user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def _on_key(self, ncode, wparam, lparam):
        if ncode == 0:
            self.last_key_at = time.monotonic()
        return ctypes.windll.user32.CallNextHookEx(None, ncode, wparam, lparam)


class Bubble(QtWidgets.QWidget):
    def __init__(self):
        super().__init__(None, QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool |
                         QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.label = QtWidgets.QLabel(self)
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(320)
        self.label.setStyleSheet("""
            QLabel { background: rgba(255,255,255,235); color: #333;
                     border-radius: 10px; padding: 8px 12px;
                     font-size: 13px; }
        """)
        self.hide_timer = QtCore.QTimer(self, singleShot=True)
        self.hide_timer.timeout.connect(self.hide)

    def _anchor_pos(self, pet_rect):
        screen = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        x = min(max(pet_rect.left() + pet_rect.width() // 2 - self.width() // 2,
                    screen.left()), screen.right() + 1 - self.width())
        y = pet_rect.top() - self.height() - 8
        if y < screen.top():
            y = pet_rect.bottom() + 8
        return x, y

    def follow(self, pet_rect):
        """Re-anchor above the pet as it moves."""
        if self.isVisible():
            self.move(*self._anchor_pos(pet_rect))

    def show_text(self, text, pet_rect):
        self.label.setText(text)
        self.label.adjustSize()
        self.resize(self.label.sizeHint())
        self.move(*self._anchor_pos(pet_rect))
        self.show()
        self.hide_timer.start(8000)


class PetWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__(None, QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool |
                         QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setCursor(QtCore.Qt.OpenHandCursor)

        cfg = {"pet": "paimon-v2", "zoom": 1.0, "autonomy": "lively",
               "resident": True, "hover_fx": True, "key_fx": True,
               "x": None, "y": None}
        try:
            cfg.update(json.load(open(STATE_FILE, encoding="utf-8")))
        except Exception:
            pass
        self.config = cfg
        self.pets = discover_pets()
        info = next((p for p in self.pets if p["name"] == cfg["pet"]),
                    self.pets[0] if self.pets else None)
        self.pet = Pet(info, cfg["zoom"])
        self.static = reduced_motion()

        self.label = QtWidgets.QLabel(self)
        # playlist player: list of (row, frame, duration_ms), loop_from index
        self.playlist = []
        self.loop_from = 0
        self.play_idx = 0
        self.frame_gen = 0
        self.play_mode = None
        self.clip_key = "idle"
        # agent aggregation: session_id -> logical state
        self.sessions = {}
        self.session_seen = {}
        self.agg_state = None
        self.control = "idle"            # idle | autonomous | interacting | dragging
        self.last_interaction = time.monotonic()
        self.cooldowns = {}
        self.pending_dbl = None          # scheduled double-action (autonomy)
        self.move_state = None           # (dx, remaining_px)
        self._work_rot_seq = 0
        self._drag_off = None
        self._press_pos = None
        self._dragged = False
        self._drag_dx = 0
        self._move_gen = 0
        self._pressed_at = 0.0
        self._last_click_at = 0.0
        self._last_hover_at = 0.0
        self.key_burst_until = 0.0
        self._last_key_seen = 0.0
        self._last_key_clip_at = 0.0
        self.started_at = time.monotonic()
        self.missed_scans = 0
        self.zcode_gone_handled = False
        self.bubble = Bubble()
        self.kb = KeyboardMonitor()
        self.kb.install()

        self.sock = QtNetwork.QUdpSocket(self)
        bound = self.sock.bind(QtNetwork.QHostAddress("127.0.0.1"), PORT,
                               QtNetwork.QAbstractSocket.DontShareAddress)
        if not bound:
            log("another daemon owns the port, exiting")
            sys.exit(0)
        self.sock.readyRead.connect(self.on_udp)

        self.sched_timer = QtCore.QTimer(self, timeout=self.scheduler_tick)
        self.sched_timer.start(300)
        self.key_timer = QtCore.QTimer(self, timeout=self.key_poll)
        self.key_timer.start(200)
        self.proc = QtCore.QTimer(self, timeout=self.scan_processes)
        self.proc.start(PROC_SCAN_MS)
        QtWidgets.QApplication.instance().aboutToQuit.connect(self.kb.uninstall)

        avail = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        x, y = cfg["x"], cfg["y"]
        if x is None or y is None or not avail.contains(QtCore.QPoint(x, y)):
            x = int(avail.left() + avail.width() * 0.72 - self.pet.size[0] / 2)
            y = avail.bottom() + 1 - 96 - self.pet.size[1]
            x = max(avail.left() + 32, min(x, avail.right() + 1 - 32 - self.pet.size[0]))
        self.setGeometry(x, y, *self.pet.size)
        self.compose("idle", "boot")
        # paint the first frame BEFORE show(): a translucent window shown empty
        # can end up with a stale, fully-transparent layered surface
        self.show_frame()
        self.show()

    # ---------- official playback engine ----------

    def available(self, key):
        return CLIPS[key]["row"] in self.pet.rows

    def pick_first(self, candidates):
        for key in candidates:
            if self.available(key):
                return key
        return "idle"

    def _clip_frames(self, key):
        spec = CLIPS[key]
        row = spec["row"]
        frames = self.pet.rows[row]
        dur = round(spec["loop_ms"] / len(frames))
        return [(row, i, dur) for i in range(len(frames))]

    def compose(self, key, reason, mode="state", force=False):
        """Build the playlist. mode 'state': [clip x3, idle fallback] (terminal
        states and one-shot interactions; the official renderer slows the
        fallback ~6x, skipped — see codex#28995). mode 'loop': plain continuous
        loop (persistent states; the 3-loop-then-idle fallback made working
        pets look idle). force=True restarts even when the same clip is already
        playing — one-shot interactions (click/hover/keyboard) must react every
        time; without it the anti-churn early return swallows them."""
        if not self.available(key):
            key = "idle"
        if (not force and key == self.clip_key
                and self.playlist and self.play_mode == mode):
            return
        log("clip:", key, "reason:", reason, "mode:", mode)
        self.clip_key = key
        self.play_mode = mode
        self.frame_gen += 1
        if self.static:
            row, frame, _ = self._clip_frames(key)[0]
            self.playlist = [(row, frame, 10 ** 9)]
            self.loop_from = 0
            self.play_idx = 0
        elif mode == "loop":
            part = self._clip_frames(key)
            self.playlist = part
            self.loop_from = 0
            self.play_idx = 0
        else:
            part = self._clip_frames(key) * STATE_LOOPS
            # the idle fallback draws from the v2 bonus rows too, so
            # float/look get regular airtime instead of never appearing
            fallback = random.choice([c for c in ("idle", "float", "look")
                                      if self.available(c)] or ["idle"])
            self.playlist = part + self._clip_frames(fallback)
            self.loop_from = len(part)
            self.play_idx = 0
        self.show_frame()
        self.kick_frame_chain()

    def kick_frame_chain(self):
        gen = self.frame_gen
        self._schedule_next()

    def _schedule_next(self):
        if self.static or not self.playlist:
            return
        duration = self.playlist[self.play_idx][2]
        gen = self.frame_gen
        QtCore.QTimer.singleShot(duration, lambda: self.advance_frame(gen))

    def advance_frame(self, gen):
        if gen != self.frame_gen:
            return
        self.play_idx += 1
        if self.play_idx >= len(self.playlist):
            self.play_idx = self.loop_from
        self.show_frame()
        self._schedule_next()

    def show_frame(self):
        row, frame, _ = self.playlist[self.play_idx]
        frames = self.pet.scaled.get(row) or self.pet.scaled[0]
        self.label.setGeometry(0, 0, *self.pet.size)
        self.label.setPixmap(frames[frame % len(frames)])
        self.label.show()

    # ---------- agent aggregation (official 4 states) ----------

    def bubble_for(self, state, payload, label):
        if state == "ready":
            text = None
            if payload:
                try:
                    raw = json.loads(payload).get("last_assistant_message") or ""
                    if raw:
                        text = clean_text(raw)
                except Exception:
                    pass
            return f"{label}：{text or '任务完成！'}"
        if state == "needs_input":
            return f"{label}：等待你的输入"
        if state == "blocked":
            return f"{label}：任务失败"
        return None

    def _state_clip(self, agg, exclude=()):
        pool = [c for c in AGENT_STATE_CLIPS[agg]
                if self.available(c) and c not in exclude]
        return random.choice(pool) if pool else "idle"

    def apply_state(self, reason="state"):
        agg = None
        for cand in STATE_PRIORITY:
            if cand in self.sessions.values():
                agg = cand
                break
        if agg == self.agg_state:
            return
        self.agg_state = agg
        if agg is None:
            self.control = "idle"
            self.compose("idle", "settle", mode="loop")
            return
        self.control = "interacting"
        persistent = agg in ("running", "needs_input", "thinking")
        self.compose(self._state_clip(agg, exclude=("running-left", "running-right")),
                     f"{reason}:{agg}", mode="loop" if persistent else "state")
        if agg == "running":
            self._schedule_work_rotation()

    def _schedule_work_rotation(self):
        """While working, rotate through the running pool — the community doc
        has working pets typing, pondering AND walking back and forth."""
        self._work_rot_seq += 1
        seq = self._work_rot_seq

        def rotate():
            if (seq != self._work_rot_seq or self.agg_state != "running"
                    or self.control == "dragging"):
                return
            key = self._state_clip("running", exclude=(self.clip_key,))
            if key in ("running-left", "running-right"):
                self.walk(-1 if key == "running-left" else 1,
                          random.uniform(30, 90), "work-rotate")
            else:
                self.compose(key, "work-rotate", mode="loop")
            self._schedule_work_rotation()

        QtCore.QTimer.singleShot(int(random.uniform(*WORK_ROTATE_S) * 1000), rotate)

    def on_udp(self):
        while self.sock.hasPendingDatagrams():
            data = self.sock.receiveDatagram().data().data()
            event, _, payload = data.partition(b"\x1f")
            event = event.decode("ascii", "ignore")
            if event == "greeting":
                self.last_interaction = time.monotonic()
                if self.agg_state is None:
                    self.control = "interacting"
                    self.compose(self.pick_first(["waving", "idle"]), "greeting",
                                 force=True)
                continue
            state = EVENT_STATE.get(event)
            if not state:
                continue
            sid = "default"
            try:
                j = json.loads(payload) if payload else {}
                sid = j.get("session_id") or "default"
                if (event == "working"
                        and j.get("hook_event_name") == "PreToolUse"
                        and j.get("tool_name") == "AskUserQuestion"):
                    state = "needs_input"  # the agent is asking us something
            except Exception:
                pass
            now = time.monotonic()
            self.session_seen[sid] = now
            prev_agg = self.agg_state
            self.sessions[sid] = state
            self.apply_state("agent")
            if self.agg_state != prev_agg:
                text = self.bubble_for(self.agg_state, payload if event == "done" else b"",
                                       session_label(payload))
                if text:
                    self.bubble.show_text(text, self.frameGeometry())

    # ---------- autonomous behavior (extra, 4 levels) ----------

    def mark_interaction(self):
        self.last_interaction = time.monotonic()

    def scheduler_tick(self):
        now = time.monotonic()
        if self.key_burst_until and now >= self.key_burst_until:
            self.key_burst_until = 0.0
            if self.control == "interacting" and self.clip_key in KEYBOARD_CLIPS:
                self.apply_state()
        # drop stale sessions, then re-aggregate (ready frees up sooner)
        stale = [s for s, t in self.session_seen.items()
                 if now - t > SESSION_STUCK_S
                 or (self.sessions.get(s) == "ready" and now - t > READY_EXPIRE_S)]
        if stale:
            for s in stale:
                self.sessions.pop(s, None)
                self.session_seen.pop(s, None)
            self.apply_state("stale")
        preset = AUTONOMY_PRESETS.get(self.config.get("autonomy", "lively"))
        if preset is None:
            return
        if (self.agg_state or self.control not in ("idle", "autonomous")
                or self.move_state):
            return
        if now - self.last_interaction < preset["gate"]:
            return
        self.run_autonomous_action(now, preset)

    def run_autonomous_action(self, now, preset, chained=False):
        if self.move_state:  # never interrupt or overlap an in-flight walk
            return
        action = self.pick_action(now, preset)
        if not action:
            return
        self.cooldowns[action["key"]] = now + preset["cds"][action["cd_idx"]]
        clips = [c for c in action["clips"] if self.available(c)]
        key = random.choice(clips) if clips else "idle"
        if key == "idle":
            return
        self.control = "autonomous"
        if key in ("running-left", "running-right"):
            self.walk(-1 if key == "running-left" else 1,
                      random.uniform(*preset["dist"]),
                      f"autonomous:{action['key']}")
        else:
            self.compose(key, f"autonomous:{action['key']}", force=True)
            if not chained and random.random() < preset["dbl"]:
                # double action: chain another one when this clip settles
                QtCore.QTimer.singleShot(
                    int(sum(d for _, _, d in self._clip_frames(key)) * STATE_LOOPS),
                    lambda: (self.control == "autonomous" and not self.move_state
                             and self.run_autonomous_action(time.monotonic(), preset, True)))

    def pick_action(self, now, preset):
        cands = [a for a in SCHEDULER_ACTIONS
                 if self.cooldowns.get(a["key"], 0) <= now
                 and any(self.available(c) for c in a["clips"])]
        total = sum(a["weight"] for a in cands)
        if total <= 0:
            return None
        cursor = random.random() * total
        for a in cands:
            cursor -= a["weight"]
            if cursor <= 0:
                return a
        return cands[-1]

    def walk(self, dx, dist, reason):
        """Start a short walk. The direction flips away from an edge with no
        room (the pet lives near the right side, so unchecked random walks
        read as 'always running left': right-walks clamp in place while
        left-walks travel the whole screen)."""
        avail = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        room_left = self.x() - avail.left()
        room_right = avail.right() + 1 - self.width() - self.x()
        if dx > 0 and room_right < 80:
            dx = -1
        elif dx < 0 and room_left < 80:
            dx = 1
        self.compose(self.pick_first(["running-right" if dx > 0 else "running-left"]),
                     reason, mode="loop")
        self._move_gen += 1  # invalidate any walk chain still in flight
        self.move_state = (dx, dist)
        self.move_step(time.monotonic(), self._move_gen)

    def move_step(self, t0, gen):
        if not self.move_state or gen != self._move_gen:
            return
        now = time.monotonic()
        dx, remaining = self.move_state
        step = MOVE_SPEED * (now - t0)
        remaining -= step
        avail = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        new_x = self.x() + dx * step
        min_x, max_x = avail.left(), avail.right() + 1 - self.width()
        if new_x <= min_x:
            new_x, dx = min_x, 1        # bounce off the edge instead of
        elif new_x >= max_x:            # running in place against it
            new_x, dx = max_x, -1
        if dx != self.move_state[0]:
            self.compose(self.pick_first(["running-right" if dx > 0 else "running-left"]),
                         "bounce", mode="loop")
        self.move(int(new_x), self.y())
        if remaining <= 0:
            self.move_state = None
            self.settle()
            return
        self.move_state = (dx, remaining)
        QtCore.QTimer.singleShot(50, lambda: self.move_step(now, gen))

    def settle(self):
        self.move_state = None
        if self.agg_state:
            persistent = self.agg_state in ("running", "needs_input", "thinking")
            self.compose(self._state_clip(self.agg_state,
                                          exclude=("running-left", "running-right")),
                         "resume", mode="loop" if persistent else "state")
        else:
            self.control = "idle"
            self.compose("idle", "settle", mode="loop")

    # ---------- keyboard busy burst (extra) ----------

    def key_poll(self):
        if not self.kb.last_key_at or self.kb.last_key_at <= self._last_key_seen:
            return
        self._last_key_seen = self.kb.last_key_at
        if not self.config.get("key_fx", True):
            return
        now = time.monotonic()
        self.mark_interaction()
        if self.agg_state or self.control == "dragging":
            return
        self.key_burst_until = now + KEYBOARD_BURST_S
        if now - self._last_key_clip_at < KEYBOARD_REROLL_S:
            return
        self._last_key_clip_at = now
        self.control = "interacting"
        key = random.choice([c for c in KEYBOARD_CLIPS if self.available(c)] or ["idle"])
        self.compose(key, "keyboard", force=True)

    # ---------- lifecycle ----------

    def scan_processes(self):
        if DEBUG or time.monotonic() - self.started_at < PROC_GRACE_S:
            return
        if any_zcode_process():
            self.missed_scans = 0
            self.zcode_gone_handled = False
            return
        self.missed_scans += 1
        log("no ZCode.exe, scan", self.missed_scans)
        if self.missed_scans < 2:
            return
        if not self.config.get("resident", True):
            self.compose(self.pick_first(["waving"]), "goodbye", force=True)
            QtCore.QTimer.singleShot(1800, QtWidgets.QApplication.instance().quit)
            return
        if not self.zcode_gone_handled:
            # resident mode: pet stays, but no ZCode means no agent sessions
            self.zcode_gone_handled = True
            self.sessions.clear()
            self.session_seen.clear()
            self.apply_state("zcode-gone")

    # ---------- interaction ----------

    def enterEvent(self, e):
        self.mark_interaction()
        if not self.config.get("hover_fx", True):
            return
        now = time.monotonic()
        if (self.agg_state is None and self.control != "dragging"
                and now - self._last_hover_at > HOVER_COOLDOWN_S):
            self._last_hover_at = now
            self.control = "interacting"
            self.compose(self.pick_first(["jumping", "idle"]), "hover", force=True)

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self.mark_interaction()
            self._pressed_at = time.monotonic()
            self._drag_off = e.globalPosition().toPoint() - self.pos()
            self._press_pos = self.pos()
            self._dragged = False
            self._drag_dx = 0

    def mouseMoveEvent(self, e):
        if self._drag_off is None:
            return
        p = e.globalPosition().toPoint() - self._drag_off
        # threshold against the press anchor: comparing to self.pos() would
        # only see per-event cursor deltas, and slow drags would never count
        if not self._dragged and (p - self._press_pos).manhattanLength() > 4:
            self._dragged = True
            self.control = "dragging"
            self.move_state = None
            self.frame_gen += 1  # freeze the state chain while dragging
            self.setCursor(QtCore.Qt.ClosedHandCursor)
        if self._dragged:
            dx = p.x() - self.x()
            if dx * self._drag_dx < 0 or (dx != 0 and self._drag_dx == 0):
                self._drag_dx = dx
                self.compose(self.pick_first(["running-right" if dx > 0 else "running-left",
                                              "idle"]),
                             "drag", mode="loop")
            self.move(p)

    def mouseReleaseEvent(self, e):
        if e.button() != QtCore.Qt.LeftButton or self._drag_off is None:
            return
        self._drag_off = None
        self.mark_interaction()
        self.setCursor(QtCore.Qt.OpenHandCursor)
        held_ms = (time.monotonic() - self._pressed_at) * 1000
        if self._dragged:
            self.snap_to_edge()
            self.config["x"], self.config["y"] = self.x(), self.y()
            self.save_config()
            self._drag_dx = 0
            self.settle()
        elif held_ms < CLICK_MS:
            self.bubble.hide()
            focus_zcode()
            self._click_reaction()

    def _click_reaction(self):
        """Click waves; a second click within the system double-click interval
        jumps (reference interactions: click -> waving, doubleClick -> jumping)."""
        now = time.monotonic()
        dbl = (now - self._last_click_at) * 1000 < QtWidgets.QApplication.doubleClickInterval()
        self._last_click_at = now
        if self.agg_state is None:
            self.control = "interacting"
            self.compose(self.pick_first(["jumping", "waving"] if dbl else ["waving", "idle"]),
                         "double-click" if dbl else "greet-on-click", force=True)

    def moveEvent(self, e):
        self.bubble.follow(self.frameGeometry())

    def snap_to_edge(self):
        avail = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        dists = [
            (abs(self.y() + self.height() - (avail.bottom() + 1)), "bottom"),
            (abs(self.x() - avail.left()), "left"),
            (abs(avail.right() + 1 - (self.x() + self.width())), "right"),
            (abs(self.y() - avail.top()), "top"),
        ]
        d, edge = min(dists)
        if d > SNAP_PX:
            return
        if edge == "bottom":
            self.move(self.x(), avail.bottom() + 1 - self.height())
        elif edge == "left":
            self.move(avail.left(), self.y())
        elif edge == "right":
            self.move(avail.right() + 1 - self.width(), self.y())
        else:
            self.move(self.x(), avail.top())

    def contextMenuEvent(self, e):
        self.mark_interaction()
        m = QtWidgets.QMenu(self)
        switch = m.addMenu("换宠物")
        for p in self.pets:
            act = switch.addAction(p["meta"].get("displayName", p["name"]))
            act.setCheckable(True)
            act.setChecked(p["name"] == self.pet.info["name"])
            act.triggered.connect(lambda _, p=p: self.switch_pet(p))
        m.addAction("重载宠物", self.reload_pets)
        size = m.addMenu("大小")
        for z in (0.5, 0.75, 1.0, 1.5):
            act = size.addAction(f"{z:g}x")
            act.setCheckable(True)
            act.setChecked(z == self.config["zoom"])
            act.triggered.connect(lambda _, z=z: self.set_zoom(z))
        auto = m.addMenu("自主动作")
        for key, name in (("off", "关"), ("mild", "温和"), ("lively", "活泼"),
                          ("hyper", "超活泼")):
            act = auto.addAction(name)
            act.setCheckable(True)
            act.setChecked(key == self.config.get("autonomy", "lively"))
            act.triggered.connect(lambda _, k=key: self.set_autonomy(k))
        fx = m.addMenu("加成")
        for key, name in (("hover_fx", "悬停跳跃"), ("key_fx", "键盘反应")):
            act = fx.addAction(name)
            act.setCheckable(True)
            act.setChecked(self.config.get(key, True))
            act.triggered.connect(lambda _, k=key: self.toggle_fx(k))
        res = m.addAction("常驻（ZCode 关闭后留在桌面）")
        res.setCheckable(True)
        res.setChecked(self.config.get("resident", True))
        res.triggered.connect(lambda: self.toggle_resident())
        m.addSeparator()
        m.addAction("退出", QtWidgets.QApplication.instance().quit)
        m.exec(e.globalPos())

    def reload_pets(self):
        try:
            pets = discover_pets()
            if not pets:
                raise ValueError("没有找到任何宠物")
            info = next((p for p in pets if p["name"] == self.pet.info["name"]),
                        pets[0])
            self.pet = Pet(info, self.config["zoom"])
            self.pets = pets
            self.config["pet"] = info["name"]
            self.frame_gen += 1
            self.compose("idle", "reloaded", mode="loop")
            self.apply_state("reloaded")
            self.save_config()
            self.bubble.show_text(f"已重载 {len(pets)} 只宠物", self.frameGeometry())
        except Exception as ex:
            log("reload failed:", ex)
            self.bubble.show_text(f"重载失败：{ex}", self.frameGeometry())

    def switch_pet(self, info):
        try:
            self.pet = Pet(info, self.config["zoom"])
        except Exception as ex:
            log("switch failed:", ex)
            return
        self.config["pet"] = info["name"]
        self.resize(*self.pet.size)
        self.frame_gen += 1
        self.compose("idle", "switch-pet", mode="loop")
        self.apply_state("switch-pet")
        self.save_config()

    def set_zoom(self, z):
        self.config["zoom"] = z
        self.pet.set_zoom(z)
        self.resize(*self.pet.size)
        self.show_frame()
        self.save_config()

    def set_autonomy(self, key):
        self.config["autonomy"] = key
        self.save_config()

    def toggle_fx(self, key):
        self.config[key] = not self.config.get(key, True)
        self.save_config()

    def toggle_resident(self):
        self.config["resident"] = not self.config.get("resident", True)
        self.save_config()
        if not self.config["resident"]:
            self.missed_scans = 0
            if not any_zcode_process():
                # turning residency off while ZCode is already gone: leave now
                self.compose(self.pick_first(["waving"]), "goodbye", force=True)
                QtCore.QTimer.singleShot(1800, QtWidgets.QApplication.instance().quit)

    def save_config(self):
        try:
            os.makedirs(USER_PETS_DIR, exist_ok=True)
            json.dump(self.config, open(STATE_FILE, "w", encoding="utf-8"))
        except Exception as ex:
            log("save config failed:", ex)


def any_zcode_process():
    """In-process Toolhelp32 scan for ZCode.exe. Any failure assumes ZCode is
    alive: a scan problem must never cost the pet its life."""
    try:
        k32 = ctypes.windll.kernel32

        class PE32(ctypes.Structure):  # PROCESSENTRY32W
            _fields_ = [("dwSize", ctypes.c_uint), ("cntUsage", ctypes.c_uint),
                        ("th32ProcessID", ctypes.c_uint),
                        ("th32DefaultHeapID", ctypes.c_size_t),  # ULONG_PTR
                        ("th32ModuleID", ctypes.c_uint), ("cntThreads", ctypes.c_uint),
                        ("th32ParentProcessID", ctypes.c_uint),
                        ("pcPriClassBase", ctypes.c_int), ("dwFlags", ctypes.c_uint),
                        ("szExeFile", ctypes.c_wchar * 260)]

        snap = k32.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
        if snap in (0, -1):
            return True
        entry = PE32()
        entry.dwSize = ctypes.sizeof(PE32)
        found = False
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == "zcode.exe":
                found = True
                break
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
        k32.CloseHandle(snap)
        return found
    except Exception as ex:
        log("process scan failed:", ex)
        return True


def focus_zcode():
    """Raise a visible window whose title contains 'zcode'."""
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def on_win(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if "zcode" in buf.value.lower():
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(on_win, 0)
    if found:
        user32.SetForegroundWindow(found[0])


def main():
    def crash_log(exc_type, exc, tb):
        import traceback
        try:
            os.makedirs(USER_PETS_DIR, exist_ok=True)
            with open(os.path.join(USER_PETS_DIR, "zpet-crash.log"), "a",
                      encoding="utf-8") as f:
                f.write("".join(traceback.format_exception(exc_type, exc, tb)) + "\n")
        except Exception:
            pass
    sys.excepthook = crash_log
    app = QtWidgets.QApplication(sys.argv)
    win = PetWindow()  # keep referenced: an unparented QWidget dies with its Python wrapper
    rc = app.exec()
    sys.exit(rc)


if __name__ == "__main__":
    main()
