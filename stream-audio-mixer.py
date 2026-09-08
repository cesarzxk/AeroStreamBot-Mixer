#!/usr/bin/env python3
"""
Stream Audio Mixer GUI - Standalone desktop app for PipeWire audio routing.
Aero-themed glassy UI with Start/Teardown controls and volume sliders for desktop + mic.
"""

import sys
import subprocess
import re
import os
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton, QSlider,
    QLabel, QVBoxLayout, QHBoxLayout, QFrame, QListWidget, QListWidgetItem,
    QLineEdit, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPalette


# ---------------------------------------------------------------------------
# App blocklist — sink-inputs whose application name matches any of these
# (case-insensitive substring) will be rerouted to stream-block instead of
# flowing into stream-mix.  Add/remove entries here, or use the UI at runtime.
# ---------------------------------------------------------------------------

BLOCKED_APPS: list[str] = [
    "discord",
    "teams",
    "zoom",
]


# ---------------------------------------------------------------------------
# pactl helpers
# ---------------------------------------------------------------------------

def run_pactl(*args):
    try:
        r = subprocess.run(['pactl'] + list(args), capture_output=True, text=True, timeout=5)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return -1, "", "pactl not found"
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def get_default_sink():
    rc, out, _ = run_pactl("info")
    for line in out.splitlines():
        if "Default Sink:" in line:
            return line.split(":", 1)[1].strip()
    return None


def get_default_source():
    rc, out, _ = run_pactl("info")
    for line in out.splitlines():
        if "Default Source:" in line:
            return line.split(":", 1)[1].strip()
    return None


# ---------------------------------------------------------------------------
# Sink-input app enumeration & blocklist enforcement
# ---------------------------------------------------------------------------

def list_sink_inputs():
    """
    Return a list of dicts with keys: idx, sink_id, app_name, binary, pid.
    Parses `pactl list sink-inputs` with full Properties block.
    """
    rc, out, _ = run_pactl("list", "sink-inputs")
    inputs = []
    current = {}
    in_props = False

    def _flush():
        if current.get("idx") is not None:
            inputs.append(dict(current))

    for line in out.splitlines():
        s = line.strip()
        if s.startswith("Sink Input #"):
            _flush()
            current = {
                "idx": s.split("#")[1].strip(),
                "sink_id": None,
                "app_name": "",
                "binary": "",
                "pid": "",
            }
            in_props = False
        elif current.get("idx") is not None:
            if not in_props and s.startswith("Sink:"):
                current["sink_id"] = s.split(":", 1)[1].strip()
            elif s.startswith("Properties:"):
                in_props = True
            elif in_props:
                # application.name = "Discord"
                m = re.match(r'application\.name\s*=\s*"(.+)"', s)
                if m:
                    current["app_name"] = m.group(1)
                m = re.match(r'application\.process\.binary\s*=\s*"(.+)"', s)
                if m:
                    current["binary"] = m.group(1)
                m = re.match(r'application\.process\.id\s*=\s*"(.+)"', s)
                if m:
                    current["pid"] = m.group(1)

    _flush()
    return inputs


def _is_blocked(si: dict) -> bool:
    """Return True if this sink-input matches any entry in BLOCKED_APPS."""
    name_lower = (si["app_name"] + " " + si["binary"]).lower()
    return any(b.lower() in name_lower for b in BLOCKED_APPS)


def has_block_sink() -> bool:
    rc, out, _ = run_pactl("list", "short", "modules")
    return any(
        "module-null-sink" in line and "sink_name=stream-block" in line
        for line in out.splitlines()
    )


def _get_sink_id_by_name(name: str):
    """Return the numeric sink ID for a given sink name, or None."""
    rc, out, _ = run_pactl("list", "short", "sinks")
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == name:
            return parts[0]
    return None


def ensure_block_sink():
    """
    Create stream-block null sink + a loopback from stream-block.monitor →
    default_sink, so blocked apps are still audible locally but their audio
    never enters stream-mix.  Returns the sink name or None on failure.
    """
    if has_block_sink():
        return _get_sink_id_by_name("stream-block")

    rc, out, _ = run_pactl(
        "load-module", "module-null-sink",
        "sink_name=stream-block",
        "sink_properties=device.description=Stream block (filtered apps)"
    )
    if rc != 0:
        return None

    # Route stream-block back to speakers so the local user still hears it
    default_sink = get_default_sink()
    if default_sink:
        run_pactl(
            "load-module", "module-loopback",
            "source=stream-block.monitor",
            f"sink={default_sink}",
            "source_dont_move=true",
        )

    return _get_sink_id_by_name("stream-block")


def teardown_block_sink():
    rc, out, _ = run_pactl("list", "short", "modules")
    to_unload = []
    for line in out.splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        mod_args = " ".join(parts[2:]) if len(parts) > 2 else ""
        if parts[1] == "module-null-sink" and "sink_name=stream-block" in mod_args:
            to_unload.append(parts[0])
        elif parts[1] == "module-loopback" and "source=stream-block.monitor" in mod_args:
            to_unload.append(parts[0])
    for mod_id in to_unload:
        run_pactl("unload-module", mod_id)


def enforce_blocklist() -> list[str]:
    """
    Move any sink-input whose app matches BLOCKED_APPS to stream-block.
    stream-block loops back to the default sink so the local user still hears
    those apps, but their audio never enters stream-mix (passthrough is clean).
    Returns list of app names moved this call.
    """
    if not BLOCKED_APPS:
        return []

    block_sink_id = ensure_block_sink()
    if block_sink_id is None:
        return []

    moved = []
    for si in list_sink_inputs():
        if not _is_blocked(si):
            continue
        # Already on stream-block — leave it alone
        block_current = _get_sink_id_by_name("stream-block")
        if block_current and si["sink_id"] == block_current:
            continue
        rc, _, _ = run_pactl("move-sink-input", si["idx"], "stream-block")
        if rc == 0:
            moved.append(si["app_name"] or si["binary"] or f"#{si['idx']}")
    return moved


def get_blocked_active() -> list[str]:
    """Return app names of sink-inputs currently parked on stream-block."""
    block_id = _get_sink_id_by_name("stream-block")
    if not block_id:
        return []
    result = []
    for si in list_sink_inputs():
        if si["sink_id"] == block_id:
            result.append(si["app_name"] or si["binary"] or f"#{si['idx']}")
    return result


def get_sink_input_for_module(module_id):
    rc, out, _ = run_pactl("list", "sink-inputs")
    current_idx = None
    in_props = False
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("Sink Input #"):
            current_idx = s.split("#")[1].strip()
            in_props = False
        elif s.startswith("Properties:"):
            in_props = True
        elif in_props and f'pulse.module.id = "{module_id}"' in s:
            return current_idx
    return None


def get_sink_input_volume(idx):
    rc, out, _ = run_pactl("list", "sink-inputs")
    in_target = False
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("Sink Input #"):
            in_target = s.split("#")[1].strip() == str(idx)
        elif in_target and s.startswith("Volume:"):
            m = re.search(r'(\d+)%', s)
            if m:
                return int(m.group(1))
    return None


def get_sink_input_mute(idx):
    rc, out, _ = run_pactl("list", "sink-inputs")
    in_target = False
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("Sink Input #"):
            in_target = s.split("#")[1].strip() == str(idx)
        elif in_target and s.startswith("Mute:"):
            return "yes" in s.lower()
    return False


def set_sink_input_volume(idx, pct):
    pct = max(0, min(200, int(pct)))
    run_pactl("set-sink-input-volume", str(idx), f"{pct}%")


def set_sink_input_mute(idx, mute):
    run_pactl("set-sink-input-mute", str(idx), "1" if mute else "0")


# ---------------------------------------------------------------------------
# Discover module IDs from the running module list (no state file needed)
# ---------------------------------------------------------------------------

def discover_loopback_modules():
    """
    Parse pactl list short modules to find loopback and null-sink modules
    associated with stream-mix. Returns (desktop_mod, mic_mod) or (None, None).
    Heuristic: the module whose source contains 'monitor' is desktop.
    """
    rc, out, _ = run_pactl("list", "short", "modules")
    desktop_mod = None
    mic_mod = None

    for line in out.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 3:
            parts = line.strip().split()
        if len(parts) < 3:
            continue
        mod_id = parts[0]
        mod_name = parts[1]
        mod_args = " ".join(parts[2:])

        if mod_name == "module-loopback" and "sink=stream-mix" in mod_args:
            if ".monitor" in mod_args:
                desktop_mod = mod_id
            else:
                mic_mod = mod_id

    return desktop_mod, mic_mod


def has_null_sink():
    """Check if the stream-mix null sink is loaded."""
    rc, out, _ = run_pactl("list", "short", "modules")
    for line in out.splitlines():
        if "module-null-sink" in line and "sink_name=stream-mix" in line:
            return True
    return False


# ---------------------------------------------------------------------------
# Setup / Teardown
# ---------------------------------------------------------------------------

def setup_mixer():
    default_sink = get_default_sink()
    default_source = get_default_source()
    if not default_sink or not default_source:
        return False, "Could not find default sink or source"

    if has_null_sink():
        return False, "stream-mix already exists"

    # Create null sink
    rc, out, _ = run_pactl(
        "load-module", "module-null-sink",
        "sink_name=stream-mix",
        "sink_properties=device.description=Stream audio mix (desktop + mic)"
    )
    if rc != 0:
        return False, f"Failed to create null sink: {out}"

    # Desktop loopback (from default sink monitor)
    desktop_source = f"{default_sink}.monitor"
    rc, out, _ = run_pactl(
        "load-module", "module-loopback",
        f"source={desktop_source}",
        "sink=stream-mix",
        "source_dont_move=true",
        "sink_dont_move=true"
    )
    if rc != 0:
        return False, f"Failed to create desktop loopback: {out}"
    desktop_mod = out.strip()

    # Mic loopback
    rc, out, _ = run_pactl(
        "load-module", "module-loopback",
        f"source={default_source}",
        "sink=stream-mix",
        "source_dont_move=true",
        "sink_dont_move=true"
    )
    if rc != 0:
        return False, f"Failed to create mic loopback: {out}"
    mic_mod = out.strip()

    # Save state file as fallback / for CLI scripts
    state_path = os.path.expanduser("~/.stream-audio-ids")
    with open(state_path, "w") as f:
        f.write(f"{desktop_mod} {mic_mod}")

    # Immediately enforce blocklist so filtered apps never touch stream-mix
    enforce_blocklist()

    return True, f"Desktop: {desktop_mod}  Mic: {mic_mod}"


def teardown_mixer():
    """
    Unload all loopback and null-sink modules associated with stream-mix.
    Uses pactl list short modules and checks the raw argument string.
    """
    rc, out, _ = run_pactl("list", "short", "modules")
    target_mods = []

    for line in out.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 3:
            parts = line.strip().split()
        if len(parts) < 3:
            continue
        mod_id = parts[0]
        mod_name = parts[1]
        mod_args = " ".join(parts[2:])

        # Match loopbacks targeting stream-mix
        if mod_name == "module-loopback" and "sink=stream-mix" in mod_args:
            target_mods.append(mod_id)
        # Match null-sink for stream-mix
        if mod_name == "module-null-sink" and "sink_name=stream-mix" in mod_args:
            target_mods.append(mod_id)

    for mod_id in target_mods:
        run_pactl("unload-module", mod_id)

    teardown_block_sink()

    state_path = os.path.expanduser("~/.stream-audio-ids")
    if os.path.exists(state_path):
        os.remove(state_path)

    return True, f"Unloaded {len(target_mods)} modules"


# ---------------------------------------------------------------------------
# Polled state
# ---------------------------------------------------------------------------

def get_mixer_state():
    active = has_null_sink()
    desktop_mod, mic_mod = discover_loopback_modules() if active else (None, None)

    desktop_vol = 50
    mic_vol = 50
    desktop_muted = False
    mic_muted = False

    if desktop_mod:
        idx = get_sink_input_for_module(desktop_mod)
        if idx:
            v = get_sink_input_volume(idx)
            if v is not None:
                desktop_vol = v
            desktop_muted = get_sink_input_mute(idx)

    if mic_mod:
        idx = get_sink_input_for_module(mic_mod)
        if idx:
            v = get_sink_input_volume(idx)
            if v is not None:
                mic_vol = v
            mic_muted = get_sink_input_mute(idx)

    default_sink = get_default_sink()
    default_source = get_default_source()

    return {
        "active": active,
        "desktop_vol": desktop_vol,
        "mic_vol": mic_vol,
        "desktop_muted": desktop_muted,
        "mic_muted": mic_muted,
        "desktop_mod": desktop_mod,
        "mic_mod": mic_mod,
        "default_sink": default_sink,
        "default_source": default_source,
        "blocked_active": get_blocked_active() if active else [],
    }


# ---------------------------------------------------------------------------
# Aero / Glassy stylesheet
# ---------------------------------------------------------------------------

AERO_QSS = """
QMainWindow {
    background: transparent;
}

/* ── Main panel: frosted pearl glass ── */
#centralWidget {
    background: qlineargradient(x1:0, y1:0, x2:0.3, y2:1,
        stop:0   rgba(255, 255, 255, 210),
        stop:0.4 rgba(220, 240, 255, 200),
        stop:1   rgba(185, 220, 250, 210));
    border: 1px solid rgba(255, 255, 255, 200);
    border-bottom-color: rgba(100, 160, 220, 120);
    border-right-color:  rgba(100, 160, 220, 100);
    border-radius: 12px;
}

/* ── Title ── */
#titleLabel {
    color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(20,  90, 160, 255),
        stop:1 rgba(10,  50, 120, 255));
    font-size: 19px;
    font-weight: bold;
    font-family: "Segoe UI", "Ubuntu", sans-serif;
    padding: 6px 0px 2px 0px;
}

/* ── Status ── */
#statusLabel {
    color: rgba(30, 80, 150, 210);
    font-size: 12px;
    font-family: "Segoe UI", "Ubuntu", sans-serif;
    padding: 2px 0px;
}

/* ── Device / hint labels ── */
#deviceLabel {
    color: rgba(50, 100, 160, 160);
    font-size: 11px;
    font-family: "Segoe UI", "Ubuntu", sans-serif;
    padding: 2px 0px;
}

/* ── Channel section headings ── */
#channelLabel {
    color: rgba(15, 70, 150, 230);
    font-size: 13px;
    font-weight: bold;
    font-family: "Segoe UI", "Ubuntu", sans-serif;
    padding: 4px 0px 0px 0px;
}

/* ── Volume percentage readout ── */
#volPct {
    color: rgba(10, 80, 170, 220);
    font-size: 13px;
    font-weight: bold;
    font-family: "Segoe UI", "Ubuntu", sans-serif;
}

/* ── Separator ── */
QFrame#separator {
    color: rgba(120, 180, 230, 90);
    max-height: 1px;
}

/* ══════════════════════════════════
   BUTTONS — Aero glass pill style
   ══════════════════════════════════ */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0    rgba(255, 255, 255, 240),
        stop:0.45 rgba(195, 228, 252, 230),
        stop:0.5  rgba(160, 210, 248, 220),
        stop:1    rgba(120, 185, 240, 230));
    color: rgba(15, 60, 130, 255);
    border: 1px solid rgba(100, 160, 215, 180);
    border-bottom-color: rgba(60, 120, 190, 200);
    border-radius: 8px;
    padding: 9px 24px;
    font-size: 13px;
    font-weight: bold;
    font-family: "Segoe UI", "Ubuntu", sans-serif;
    min-width: 115px;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0    rgba(255, 255, 255, 255),
        stop:0.45 rgba(210, 238, 255, 240),
        stop:0.5  rgba(175, 220, 255, 230),
        stop:1    rgba(130, 195, 250, 240));
    border-color: rgba(80, 140, 210, 220);
    color: rgba(10, 50, 120, 255);
}
QPushButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0    rgba(140, 195, 240, 230),
        stop:0.5  rgba(170, 215, 250, 220),
        stop:1    rgba(210, 235, 255, 230));
    border-color: rgba(60, 110, 180, 200);
    padding-top: 10px;
    padding-bottom: 8px;
}
QPushButton:disabled {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(235, 240, 245, 160),
        stop:1 rgba(210, 220, 230, 160));
    color: rgba(130, 155, 180, 140);
    border-color: rgba(170, 190, 210, 100);
}

/* Teardown — warm coral glass */
#teardownBtn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0    rgba(255, 255, 255, 235),
        stop:0.45 rgba(255, 210, 205, 225),
        stop:0.5  rgba(248, 175, 165, 215),
        stop:1    rgba(235, 130, 115, 225));
    border-color: rgba(210, 100, 85, 170);
    color: rgba(130, 30, 20, 240);
}
#teardownBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0    rgba(255, 255, 255, 255),
        stop:0.45 rgba(255, 220, 215, 240),
        stop:0.5  rgba(252, 185, 175, 230),
        stop:1    rgba(242, 145, 130, 240));
    border-color: rgba(200, 80, 65, 200);
}
#teardownBtn:pressed {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0    rgba(235, 130, 115, 230),
        stop:0.5  rgba(248, 165, 155, 220),
        stop:1    rgba(255, 210, 205, 230));
}

/* ══════════════════════════════════
   SLIDERS — aqua glass track + orb
   ══════════════════════════════════ */
QSlider::groove:horizontal {
    border: 1px solid rgba(120, 180, 230, 130);
    height: 7px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(180, 215, 245, 160),
        stop:1 rgba(210, 235, 255, 200));
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(50,  160, 220, 200),
        stop:1 rgba(100, 200, 245, 210));
    border: 1px solid rgba(60, 150, 210, 140);
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0    rgba(255, 255, 255, 255),
        stop:0.4  rgba(210, 238, 255, 240),
        stop:0.5  rgba(155, 210, 248, 230),
        stop:1    rgba(90,  170, 235, 240));
    border: 1px solid rgba(70, 140, 210, 190);
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
}
QSlider::handle:horizontal:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0    rgba(255, 255, 255, 255),
        stop:0.4  rgba(220, 245, 255, 245),
        stop:0.5  rgba(170, 225, 255, 235),
        stop:1    rgba(100, 185, 245, 245));
    border-color: rgba(50, 120, 200, 220);
}
"""


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MixerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stream Audio Mixer")
        self.setFixedSize(430, 580)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)

        self.central = QWidget()
        self.central.setObjectName("centralWidget")
        self.setCentralWidget(self.central)

        self._setup_ui()
        self.setStyleSheet(AERO_QSS)

        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.poll_state)
        self.poll_timer.start(1500)

        self.drag_pos = None
        self.poll_state()

    # -- window dragging (frameless) --

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_pos:
            self.move(event.globalPos() - self.drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_pos = None

    def mouseDoubleClickEvent(self, event):
        self.close()

    # -- UI construction --

    def _setup_ui(self):
        layout = QVBoxLayout(self.central)
        layout.setSpacing(8)
        layout.setContentsMargins(20, 16, 20, 16)

        # Title
        title = QLabel("Stream Audio Mixer")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Status
        self.status_label = QLabel("Checking...")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        # Device info
        self.device_label = QLabel("")
        self.device_label.setObjectName("deviceLabel")
        self.device_label.setAlignment(Qt.AlignCenter)
        self.device_label.setWordWrap(True)
        layout.addWidget(self.device_label)

        # Separator
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        # Desktop channel
        cl1 = QLabel("Desktop Audio")
        cl1.setObjectName("channelLabel")
        layout.addWidget(cl1)

        self.desktop_slider = QSlider(Qt.Horizontal)
        self.desktop_slider.setRange(0, 200)
        self.desktop_slider.setValue(50)
        self.desktop_slider.valueChanged.connect(lambda v: self.desktop_vol_label.setText(f"{v}%"))
        self.desktop_slider.sliderReleased.connect(self._on_desktop_slider_released)
        layout.addWidget(self.desktop_slider)

        drow = QHBoxLayout()
        self.desktop_mute_btn = QPushButton("M")
        self.desktop_mute_btn.setFixedSize(32, 28)
        self.desktop_mute_btn.setCheckable(True)
        self.desktop_mute_btn.clicked.connect(self._on_desktop_mute_toggled)
        self.desktop_mute_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0    rgba(255, 255, 255, 230),
                    stop:0.45 rgba(195, 228, 252, 215),
                    stop:0.5  rgba(155, 208, 248, 205),
                    stop:1    rgba(115, 182, 238, 215));
                border: 1px solid rgba(100, 160, 215, 170);
                border-bottom-color: rgba(60, 120, 190, 190);
                border-radius: 5px;
                color: rgba(15, 60, 130, 230);
                font-weight: bold;
                font-size: 11px;
                font-family: "Segoe UI", "Ubuntu", sans-serif;
                padding: 0px;
            }
            QPushButton:checked {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0    rgba(255, 255, 255, 230),
                    stop:0.45 rgba(255, 205, 200, 220),
                    stop:0.5  rgba(248, 168, 158, 210),
                    stop:1    rgba(232, 124, 108, 220));
                border-color: rgba(210, 95, 80, 165);
                color: rgba(120, 25, 15, 230);
            }
        """)
        drow.addWidget(self.desktop_mute_btn)
        self.desktop_vol_label = QLabel("50%")
        self.desktop_vol_label.setObjectName("volPct")
        drow.addWidget(self.desktop_vol_label)
        drow.addStretch()
        layout.addLayout(drow)

        # Mic channel
        cl2 = QLabel("Microphone")
        cl2.setObjectName("channelLabel")
        layout.addWidget(cl2)

        self.mic_slider = QSlider(Qt.Horizontal)
        self.mic_slider.setRange(0, 200)
        self.mic_slider.setValue(50)
        self.mic_slider.valueChanged.connect(lambda v: self.mic_vol_label.setText(f"{v}%"))
        self.mic_slider.sliderReleased.connect(self._on_mic_slider_released)
        layout.addWidget(self.mic_slider)

        mrow = QHBoxLayout()
        self.mic_mute_btn = QPushButton("M")
        self.mic_mute_btn.setFixedSize(32, 28)
        self.mic_mute_btn.setCheckable(True)
        self.mic_mute_btn.clicked.connect(self._on_mic_mute_toggled)
        self.mic_mute_btn.setStyleSheet(self.desktop_mute_btn.styleSheet())
        mrow.addWidget(self.mic_mute_btn)
        self.mic_vol_label = QLabel("50%")
        self.mic_vol_label.setObjectName("volPct")
        mrow.addWidget(self.mic_vol_label)
        mrow.addStretch()
        layout.addLayout(mrow)

        # Separator
        sep2 = QFrame()
        sep2.setObjectName("separator")
        sep2.setFrameShape(QFrame.HLine)
        layout.addWidget(sep2)

        # -- Blocklist section --
        bl_label = QLabel("Filtered Apps (blocked from passthrough)")
        bl_label.setObjectName("channelLabel")
        layout.addWidget(bl_label)

        # List of currently-blocked-active apps (live status)
        self.blocked_active_label = QLabel("None running")
        self.blocked_active_label.setObjectName("deviceLabel")
        self.blocked_active_label.setWordWrap(True)
        layout.addWidget(self.blocked_active_label)

        # Editable blocklist
        self.blocklist_widget = QListWidget()
        self.blocklist_widget.setMaximumHeight(90)
        self.blocklist_widget.setStyleSheet("""
            QListWidget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(245, 251, 255, 200),
                    stop:1 rgba(220, 238, 252, 200));
                border: 1px solid rgba(100, 160, 215, 140);
                border-radius: 6px;
                color: rgba(15, 60, 130, 220);
                font-size: 12px;
                font-family: "Segoe UI", "Ubuntu", sans-serif;
            }
            QListWidget::item:selected {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(180, 220, 250, 210),
                    stop:1 rgba(130, 190, 240, 210));
                color: rgba(10, 45, 110, 255);
            }
        """)
        for entry in BLOCKED_APPS:
            self.blocklist_widget.addItem(QListWidgetItem(entry))
        layout.addWidget(self.blocklist_widget)

        add_row = QHBoxLayout()
        self.bl_input = QLineEdit()
        self.bl_input.setPlaceholderText("App name to block…")
        self.bl_input.setStyleSheet("""
            QLineEdit {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(245, 251, 255, 210),
                    stop:1 rgba(220, 238, 252, 210));
                border: 1px solid rgba(100, 160, 215, 150);
                border-radius: 6px;
                color: rgba(15, 55, 120, 230);
                padding: 4px 8px;
                font-size: 12px;
                font-family: "Segoe UI", "Ubuntu", sans-serif;
            }
            QLineEdit:focus {
                border-color: rgba(60, 130, 200, 220);
                background: rgba(250, 253, 255, 220);
            }
        """)
        self.bl_input.returnPressed.connect(self._on_blocklist_add)
        add_row.addWidget(self.bl_input)

        bl_add_btn = QPushButton("+")
        bl_add_btn.setFixedSize(32, 28)
        bl_add_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0    rgba(255, 255, 255, 230),
                    stop:0.45 rgba(195, 238, 210, 215),
                    stop:0.5  rgba(148, 218, 172, 205),
                    stop:1    rgba(90,  190, 130, 215));
                border: 1px solid rgba(70, 160, 105, 170);
                border-bottom-color: rgba(45, 130, 80, 190);
                border-radius: 6px;
                color: rgba(15, 80, 35, 230);
                font-weight: bold;
                font-size: 16px;
                padding: 0px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0    rgba(255, 255, 255, 245),
                    stop:0.45 rgba(210, 248, 222, 230),
                    stop:0.5  rgba(162, 228, 182, 218),
                    stop:1    rgba(100, 200, 140, 228));
            }
        """)
        bl_add_btn.clicked.connect(self._on_blocklist_add)
        add_row.addWidget(bl_add_btn)

        bl_del_btn = QPushButton("−")
        bl_del_btn.setFixedSize(32, 28)
        bl_del_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0    rgba(255, 255, 255, 230),
                    stop:0.45 rgba(255, 205, 200, 220),
                    stop:0.5  rgba(248, 165, 155, 210),
                    stop:1    rgba(232, 120, 105, 220));
                border: 1px solid rgba(205, 92, 78, 168);
                border-bottom-color: rgba(175, 65, 52, 188);
                border-radius: 6px;
                color: rgba(120, 25, 15, 230);
                font-weight: bold;
                font-size: 16px;
                padding: 0px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0    rgba(255, 255, 255, 245),
                    stop:0.45 rgba(255, 218, 213, 232),
                    stop:0.5  rgba(252, 178, 168, 222),
                    stop:1    rgba(240, 133, 118, 232));
            }
        """)
        bl_del_btn.clicked.connect(self._on_blocklist_remove)
        add_row.addWidget(bl_del_btn)
        layout.addLayout(add_row)

        # Separator before buttons
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self.start_btn)

        self.teardown_btn = QPushButton("Teardown")
        self.teardown_btn.setObjectName("teardownBtn")
        self.teardown_btn.clicked.connect(self._on_teardown)
        btn_row.addWidget(self.teardown_btn)
        layout.addLayout(btn_row)

        # Close hint
        hint = QLabel("Drag to move  ·  Double-click to close")
        hint.setObjectName("deviceLabel")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

    # -- actions --

    def _on_blocklist_add(self):
        text = self.bl_input.text().strip()
        if not text:
            return
        # Avoid duplicates
        existing = [self.blocklist_widget.item(i).text()
                    for i in range(self.blocklist_widget.count())]
        if text.lower() not in [e.lower() for e in existing]:
            BLOCKED_APPS.append(text)
            self.blocklist_widget.addItem(QListWidgetItem(text))
        self.bl_input.clear()
        enforce_blocklist()

    def _on_blocklist_remove(self):
        row = self.blocklist_widget.currentRow()
        if row < 0:
            return
        entry = self.blocklist_widget.item(row).text()
        self.blocklist_widget.takeItem(row)
        try:
            BLOCKED_APPS.remove(entry)
        except ValueError:
            # Remove case-insensitively as fallback
            for i, e in enumerate(BLOCKED_APPS):
                if e.lower() == entry.lower():
                    BLOCKED_APPS.pop(i)
                    break

    def _on_start(self):
        self.start_btn.setEnabled(False)
        self.status_label.setText("Setting up...")
        success, msg = setup_mixer()
        self.status_label.setText(f"{'OK' if success else 'FAIL'}  {msg}" if not success else "Running")
        self.start_btn.setEnabled(True)
        self.poll_state()

    def _on_teardown(self):
        self.teardown_btn.setEnabled(False)
        self.status_label.setText("Tearing down...")
        teardown_mixer()
        self.status_label.setText("Stopped")
        self.teardown_btn.setEnabled(True)
        self.poll_state()

    def _on_desktop_slider_released(self):
        state = get_mixer_state()
        if state["desktop_mod"]:
            idx = get_sink_input_for_module(state["desktop_mod"])
            if idx:
                set_sink_input_volume(idx, self.desktop_slider.value())

    def _on_mic_slider_released(self):
        state = get_mixer_state()
        if state["mic_mod"]:
            idx = get_sink_input_for_module(state["mic_mod"])
            if idx:
                set_sink_input_volume(idx, self.mic_slider.value())

    def _on_desktop_mute_toggled(self):
        state = get_mixer_state()
        if state["desktop_mod"]:
            idx = get_sink_input_for_module(state["desktop_mod"])
            if idx:
                set_sink_input_mute(idx, self.desktop_mute_btn.isChecked())

    def _on_mic_mute_toggled(self):
        state = get_mixer_state()
        if state["mic_mod"]:
            idx = get_sink_input_for_module(state["mic_mod"])
            if idx:
                set_sink_input_mute(idx, self.mic_mute_btn.isChecked())

    # -- polling --

    def poll_state(self):
        state = get_mixer_state()

        # Enforce blocklist on every poll tick
        if state["active"]:
            enforce_blocklist()

        if state["active"]:
            self.status_label.setText("Running")
            self.start_btn.setEnabled(False)
            self.teardown_btn.setEnabled(True)
            self.desktop_slider.setEnabled(True)
            self.mic_slider.setEnabled(True)
            self.desktop_mute_btn.setEnabled(True)
            self.mic_mute_btn.setEnabled(True)
        else:
            self.status_label.setText("Stopped")
            self.start_btn.setEnabled(True)
            self.teardown_btn.setEnabled(False)
            self.desktop_slider.setEnabled(False)
            self.mic_slider.setEnabled(False)
            self.desktop_mute_btn.setEnabled(False)
            self.mic_mute_btn.setEnabled(False)

        # Device info
        sn = state["default_sink"] or "?"
        sc = state["default_source"] or "?"
        self.device_label.setText(
            f"Sink: {sn[:50]}\nSource: {sc[:50]}"
        )

        # Blocked apps — live status
        blocked = state["blocked_active"]
        if blocked:
            self.blocked_active_label.setText("🔇 Blocked now: " + ", ".join(blocked))
        elif state["active"]:
            self.blocked_active_label.setText("✓ No blocked apps running")
        else:
            self.blocked_active_label.setText("")

        # Update sliders from actual state (block signals to avoid feedback)
        self.desktop_slider.blockSignals(True)
        self.desktop_slider.setValue(state["desktop_vol"])
        self.desktop_slider.blockSignals(False)
        self.desktop_vol_label.setText(f"{state['desktop_vol']}%")

        self.mic_slider.blockSignals(True)
        self.mic_slider.setValue(state["mic_vol"])
        self.mic_slider.blockSignals(False)
        self.mic_vol_label.setText(f"{state['mic_vol']}%")

        self.desktop_mute_btn.blockSignals(True)
        self.desktop_mute_btn.setChecked(state["desktop_muted"])
        self.desktop_mute_btn.blockSignals(False)

        self.mic_mute_btn.blockSignals(True)
        self.mic_mute_btn.setChecked(state["mic_muted"])
        self.mic_mute_btn.blockSignals(False)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(210, 232, 250))
    app.setPalette(palette)

    w = MixerWindow()
    w.show()
    sys.exit(app.exec_())