#!/usr/bin/env python3
"""
Stream Audio Mixer GUI - Standalone desktop app for PipeWire audio routing.
Aero-themed glassy UI with Start/Teardown controls and volume sliders for desktop + mic.
"""

import sys
import subprocess
import re
import os
import signal
import ctypes
import json
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton, QSlider,
    QLabel, QVBoxLayout, QHBoxLayout, QFrame, QListWidget, QListWidgetItem,
    QLineEdit, QSizePolicy, QSystemTrayIcon, QMenu, QAction, QComboBox
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPalette, QIcon, QPixmap, QPainter, QBrush, QPen


# ---------------------------------------------------------------------------
# App blocklist — sink-inputs whose application name matches any of these
# (case-insensitive substring) will be rerouted to stream-block instead of
# flowing directly into stream-mix. Add/remove entries here, or use the UI at
# runtime. The blocked sink is returned to the physical output for local
# playback, so its audio can be present in the physical sink monitor.
# ---------------------------------------------------------------------------

BLOCKED_APPS: list[str] = [
    "discord",
    "teams",
    "zoom",
]

BOT_TOKEN_FILE = os.path.join(os.path.dirname(
    os.path.abspath(__file__)), ".discord_token.txt")
BOT_LOG_FILE = os.path.join(os.path.dirname(
    os.path.abspath(__file__)), ".discord_bot.log")
BOT_VOLUME_FILE = os.path.join(os.path.dirname(
    os.path.abspath(__file__)), ".discord_bot_volume.txt")
LANGUAGE_FILE = os.path.join(os.path.dirname(
    os.path.abspath(__file__)), ".aerostream_language.txt")
TRANSLATIONS_FILE = os.path.join(os.path.dirname(
    os.path.abspath(__file__)), "translations.json")
PHYSICAL_SINK_FILE = os.path.expanduser("~/.aerostream-physical-sink")

LANGUAGE_OPTIONS = {
    "en": "EN",
    "pt": "PT",
}

DEFAULT_TRANSLATIONS = {
    "en": {
        "title": "Stream Audio Mixer",
        "language": "Language",
        "status_checking": "Checking...",
        "source_mode": "Source mode",
        "desktop_only": "Desktop only",
        "mic_plus_desktop": "Mic + Desktop",
        "desktop_audio": "Desktop Audio",
        "filtered_apps": "Filtered Apps (blocked from passthrough)",
        "none_running": "None running",
        "app_name_to_block": "App name to block…",
        "discord_bot": "Discord bot",
        "bot_token_placeholder": "Bot token (saved to .discord_token.txt)",
        "load_token": "Load token",
        "save_token": "Save token",
        "start_bot": "Start bot",
        "bot_volume": "Bot transmission volume",
        "bot_stopped": "Bot stopped",
        "start": "Start",
        "teardown": "Teardown",
        "drag_hint": "Drag to move  ·  Double-click to minimize to tray",
        "open_restore": "Open / Restore",
        "minimize_tray": "Minimize to Tray",
        "exit": "Exit",
        "running": "Running",
        "stopped": "Stopped",
        "setting_up": "Setting up...",
        "setting_up_mixer": "Setting up mixer...",
        "token_loaded": "Token loaded",
        "no_token_saved": "No token saved in .discord_token.txt",
        "enter_token": "Enter a token before saving",
        "token_saved": "Token saved to .discord_token.txt",
        "token_empty": "Token is empty. Save a token first.",
        "bot_already_running": "Bot is already running",
        "bot_starting": "Bot starting (PID {pid})...",
        "error_starting_bot": "Error starting bot: {exc}",
        "bot_stopped_exit": "Bot stopped (exit code {code})",
        "sink": "Sink",
        "source": "Source",
        "blocked_now": "🔇 Blocked now: {apps}",
        "no_blocked_apps": "✓ No blocked apps running",
        "device_status": "{sink}\n{source}",
        "check_status": "Checking...",
        "audio_setup": "Setting up...",
        "audio_running": "Running",
        "audio_stopped": "Stopped",
    },
    "pt": {
        "title": "Stream Audio Mixer",
        "language": "Idioma",
        "status_checking": "Verificando...",
        "source_mode": "Modo de origem",
        "desktop_only": "Apenas desktop",
        "mic_plus_desktop": "Microfone + Desktop",
        "desktop_audio": "Áudio do desktop",
        "filtered_apps": "Aplicativos filtrados (bloqueados no passthrough)",
        "none_running": "Nenhum em execução",
        "app_name_to_block": "Nome do app para bloquear…",
        "discord_bot": "Bot do Discord",
        "bot_token_placeholder": "Token do bot (salvo em .discord_token.txt)",
        "load_token": "Carregar token",
        "save_token": "Salvar token",
        "start_bot": "Iniciar bot",
        "bot_volume": "Volume de transmissão do bot",
        "bot_stopped": "Bot parado",
        "start": "Iniciar",
        "teardown": "Encerrar",
        "drag_hint": "Arraste para mover  ·  Clique duplo para minimizar na bandeja",
        "open_restore": "Abrir / Restaurar",
        "minimize_tray": "Minimizar para a bandeja",
        "exit": "Sair",
        "running": "Em execução",
        "stopped": "Parado",
        "setting_up": "Configurando...",
        "setting_up_mixer": "Configurando mixer...",
        "token_loaded": "Token carregado",
        "no_token_saved": "Nenhum token salvo em .discord_token.txt",
        "enter_token": "Informe um token antes de salvar",
        "token_saved": "Token salvo em .discord_token.txt",
        "token_empty": "Token vazio. Salve um token primeiro.",
        "bot_already_running": "Bot já está em execução",
        "bot_starting": "Bot iniciando (PID {pid})...",
        "error_starting_bot": "Erro ao iniciar bot: {exc}",
        "bot_stopped_exit": "Bot encerrado (código de saída {code})",
        "sink": "Sink",
        "source": "Fonte",
        "blocked_now": "🔇 Bloqueado agora: {apps}",
        "no_blocked_apps": "✓ Nenhum app bloqueado em execução",
        "device_status": "{sink}\n{source}",
        "check_status": "Verificando...",
        "audio_setup": "Configurando...",
        "audio_running": "Em execução",
        "audio_stopped": "Parado",
    },
}


def load_translations(path: str = TRANSLATIONS_FILE) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {**DEFAULT_TRANSLATIONS, **data}
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return DEFAULT_TRANSLATIONS


TRANSLATIONS = load_translations()


def get_bot_command(project_dir: str, bot_python: str) -> list[str]:
    if getattr(sys, "frozen", False):
        runner_path = os.path.join(os.path.dirname(sys.executable),
                                   "discord_bot_runner")
        return [runner_path]
    return [bot_python, os.path.join(project_dir, "discord_bot_runner.py")]


STREAM_MODES = {
    "desktop": "Desktop only",
    "mic": "Mic + Desktop",
}


# ---------------------------------------------------------------------------
# pactl helpers
# ---------------------------------------------------------------------------


def resolve_loopback_source(channel: str, default_sink: str | None, default_source: str | None) -> str | None:
    """Return the PipeWire source to feed into stream-mix for the desired channel."""
    if channel == "desktop":
        return f"{default_sink}.monitor" if default_sink else None
    if channel == "mic":
        return default_source
    return None


def run_pactl(*args):
    try:
        r = subprocess.run(['pactl'] + list(args),
                           capture_output=True, text=True, timeout=5)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return -1, "", "pactl not found"
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def _terminate_bot_with_parent():
    """Ask Linux to terminate the bot if the GUI process disappears."""
    ctypes.CDLL(None).prctl(1, signal.SIGTERM)


def get_default_sink():
    rc, out, _ = run_pactl("info")
    for line in out.splitlines():
        if "Default Sink:" in line:
            return line.split(":", 1)[1].strip()
    return None


def get_default_physical_sink():
    try:
        with open(PHYSICAL_SINK_FILE, "r", encoding="utf-8") as f:
            sink = f.read().strip()
            if sink:
                return sink
    except FileNotFoundError:
        pass

    sink = get_default_sink()
    return sink if sink and not sink.startswith("stream-") else None


def get_default_source():
    rc, out, _ = run_pactl("info")
    for line in out.splitlines():
        if "Default Source:" in line:
            return line.split(":", 1)[1].strip()
    return None


def load_discord_token(path: str = BOT_TOKEN_FILE) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def save_discord_token(token: str, path: str = BOT_TOKEN_FILE) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write((token or "").strip())
    os.chmod(path, 0o600)


def save_bot_volume(value: int) -> None:
    with open(BOT_VOLUME_FILE, "w", encoding="ascii") as f:
        f.write(str(max(0, min(200, int(value))) / 100))


def load_language(path: str = LANGUAGE_FILE) -> str:
    try:
        value = open(path, "r", encoding="utf-8").read().strip().lower()
    except FileNotFoundError:
        return "en"
    return value if value in LANGUAGE_OPTIONS else "en"


def save_language(language: str, path: str = LANGUAGE_FILE) -> None:
    code = (language or "en").strip().lower()
    if code not in LANGUAGE_OPTIONS:
        code = "en"
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    os.chmod(path, 0o600)


# ---------------------------------------------------------------------------
# Sink-input app enumeration & blocklist enforcement
# ---------------------------------------------------------------------------

def list_sink_inputs():
    """
    Return a list of dicts with identifying application and node properties.
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
                "node_name": "",
                "media_name": "",
                "module_id": "",
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
                m = re.match(r'node\.name\s*=\s*"(.+)"', s)
                if m:
                    current["node_name"] = m.group(1)
                m = re.match(r'media\.name\s*=\s*"(.+)"', s)
                if m:
                    current["media_name"] = m.group(1)
                m = re.match(r'application\.process\.id\s*=\s*"(.+)"', s)
                if m:
                    current["pid"] = m.group(1)
                m = re.match(r'pulse\.module\.id\s*=\s*"(.+)"', s)
                if m:
                    current["module_id"] = m.group(1)

    _flush()
    return inputs


def _is_blocked(si: dict) -> bool:
    """Return True if this sink-input matches any entry in BLOCKED_APPS."""
    name_lower = " ".join(
        si.get(key, "")
        for key in ("app_name", "binary", "node_name", "media_name")
    ).lower()
    return any(b.lower() in name_lower for b in BLOCKED_APPS)


def _get_stream_mix_sink_id():
    return _get_sink_id_by_name("stream-mix")


def _get_local_output_loopback_id():
    rc, out, _ = run_pactl("list", "short", "modules")
    for line in out.splitlines():
        parts = line.strip().split()
        if len(parts) >= 3 and parts[1] == "module-loopback":
            args = " ".join(parts[2:])
            if "source=stream-mix.monitor" in args:
                return parts[0]
    return None


def _move_sink_input(idx, sink):
    return run_pactl("move-sink-input", str(idx), sink)[0] == 0


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
    Create stream-block and route it back to the physical output. This keeps
    blocked apps audible locally while the blocklist prevents their original
    streams from entering stream-mix.
    Returns the sink name or None on failure.
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
    Keep blocked apps on the physical sink and route other desktop streams to
    stream-mix. The physical sink is not used as the capture source, so this
    does not create an audio feedback loop.
    Returns list of app names moved this call.
    """
    mix_sink = _get_stream_mix_sink_id()
    physical_sink = get_default_physical_sink()
    if not mix_sink or not physical_sink:
        return []

    local_loopback_id = _get_local_output_loopback_id()
    moved = []
    for si in list_sink_inputs():
        if si["module_id"] == str(local_loopback_id):
            continue
        target = physical_sink if _is_blocked(si) else mix_sink
        if si["sink_id"] == target:
            continue
        if _move_sink_input(si["idx"], target):
            if _is_blocked(si):
                moved.append(si["app_name"] or si["binary"] or f"#{si['idx']}")
    return moved


def get_blocked_active() -> list[str]:
    """Return app names of sink-inputs currently parked on stream-block."""
    result = []
    for si in list_sink_inputs():
        if _is_blocked(si) and si["sink_id"] == get_default_physical_sink():
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


def get_stream_mix_inputs(exclude_module=None):
    """Return sink-inputs currently routed to stream-mix."""
    mix_sink = _get_stream_mix_sink_id()
    if not mix_sink:
        return []
    return [
        item for item in list_sink_inputs()
        if item["sink_id"] == mix_sink
        and item.get("module_id") != str(exclude_module)
    ]


def get_desktop_stream_inputs(mic_module=None):
    """Return desktop application streams feeding the bot mix."""
    return [
        item for item in get_stream_mix_inputs(mic_module)
        if not _is_blocked(item)
    ]


def set_stream_inputs_volume(inputs, pct):
    for item in inputs:
        set_sink_input_volume(item["idx"], pct)


def set_stream_inputs_mute(inputs, mute):
    for item in inputs:
        set_sink_input_mute(item["idx"], mute)


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

def setup_mixer(source_mode: str = "desktop"):
    default_sink = get_default_sink()
    default_source = get_default_source()
    if not default_sink or not default_source:
        return False, "Could not find default sink or source"

    if source_mode not in STREAM_MODES:
        return False, f"Unsupported source mode: {source_mode}"

    if has_null_sink():
        return False, "stream-mix already exists"

    with open(PHYSICAL_SINK_FILE, "w", encoding="utf-8") as f:
        f.write(default_sink)

    # Create null sink
    rc, out, _ = run_pactl(
        "load-module", "module-null-sink",
        "sink_name=stream-mix",
        "sink_properties=device.description=Stream audio mix (desktop + mic)"
    )
    if rc != 0:
        return False, f"Failed to create null sink: {out}"

    desktop_mod = None
    mic_mod = None

    if source_mode in ("desktop"):
        rc, out, _ = run_pactl(
            "load-module", "module-loopback",
            "source=stream-mix.monitor",
            f"sink={default_sink}",
            "source_dont_move=true",
            "sink_dont_move=true"
        )
        if rc != 0:
            teardown_mixer()
            return False, f"Failed to create local playback loopback: {out}"
        desktop_mod = out.strip()
        run_pactl("set-default-sink", "stream-mix")
        enforce_blocklist()

    if source_mode in ("mic"):
        mic_source = resolve_loopback_source(
            "mic", default_sink, default_source)
        if not mic_source:
            return False, "Could not resolve mic source"
        rc, out, _ = run_pactl(
            "load-module", "module-loopback",
            f"source={mic_source}",
            "sink=stream-mix",
            "source_dont_move=true",
            "sink_dont_move=true"
        )
        if rc != 0:
            teardown_mixer()
            return False, f"Failed to create mic loopback: {out}"
        mic_mod = out.strip()

    # Save state file as fallback / for CLI scripts
    state_path = os.path.expanduser("~/.stream-audio-ids")
    with open(state_path, "w") as f:
        f.write(f"{desktop_mod or ''} {mic_mod or ''}".strip())

    # Immediately enforce blocklist so filtered apps never touch stream-mix
    if source_mode == "mic":
        run_pactl("set-default-sink", default_sink)
    enforce_blocklist()

    active_parts = []
    if desktop_mod:
        active_parts.append("Desktop")
    if mic_mod:
        active_parts.append("Mic")
    return True, " / ".join(active_parts) if active_parts else "No audio sources enabled"


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
        # Match the local playback loopback fed by stream-mix.monitor
        if (mod_name == "module-loopback"
                and "source=stream-mix.monitor" in mod_args):
            target_mods.append(mod_id)
        # Match null-sink for stream-mix
        if mod_name == "module-null-sink" and "sink_name=stream-mix" in mod_args:
            target_mods.append(mod_id)

    physical_sink = get_default_physical_sink()
    if physical_sink:
        run_pactl("set-default-sink", physical_sink)
        mix_sink = _get_stream_mix_sink_id()
        if mix_sink:
            for si in list_sink_inputs():
                if si["sink_id"] == mix_sink:
                    _move_sink_input(si["idx"], physical_sink)

    for mod_id in target_mods:
        run_pactl("unload-module", mod_id)

    teardown_block_sink()

    state_path = os.path.expanduser("~/.stream-audio-ids")
    if os.path.exists(state_path):
        os.remove(state_path)
    if os.path.exists(PHYSICAL_SINK_FILE):
        os.remove(PHYSICAL_SINK_FILE)

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

    desktop_inputs = get_desktop_stream_inputs(mic_mod)
    if desktop_inputs:
        volumes = [
            get_sink_input_volume(item["idx"])
            for item in desktop_inputs
        ]
        volumes = [volume for volume in volumes if volume is not None]
        if volumes:
            desktop_vol = volumes[0]
        desktop_muted = all(
            get_sink_input_mute(item["idx"])
            for item in desktop_inputs
        )

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
    min-height: 900px;
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
    letter-spacing: 0.4px;
}

/* ── Sections / cards ── */
#sectionCard {
    background: rgba(255, 255, 255, 110);
    border: 1px solid rgba(120, 180, 230, 120);
    border-radius: 10px;
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
    padding: 9px 18px;
    font-size: 13px;
    font-weight: bold;
    font-family: "Segoe UI", "Ubuntu", sans-serif;
    min-width: 110px;
}
#botActionButton {
    min-width: 0px;
    padding: 7px 10px;
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
# Tray Icon Helper
# ---------------------------------------------------------------------------

def create_aero_tray_icon() -> QIcon:
    """Generate a clean Frutiger Aero styled glass orb icon for the system tray."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # Outer glow / rim
    painter.setPen(QPen(QColor(80, 160, 230, 220), 2))
    painter.setBrush(QBrush(QColor(180, 225, 255, 230)))
    painter.drawEllipse(4, 4, size - 8, size - 8)

    # Glass highlight (upper hemisphere)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(255, 255, 255, 180)))
    painter.drawEllipse(12, 8, size - 24, (size - 24) // 2)

    # Audio wave / equalizer bars (Frutiger blue/cyan)
    painter.setBrush(QBrush(QColor(20, 80, 160, 220)))
    # Bar 1
    painter.drawRoundedRect(18, 28, 6, 16, 2, 2)
    # Bar 2 (center, taller)
    painter.drawRoundedRect(28, 20, 6, 24, 2, 2)
    # Bar 3
    painter.drawRoundedRect(38, 25, 6, 19, 2, 2)

    painter.end()
    return QIcon(pixmap)


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MixerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.language_code = load_language()
        self.setWindowTitle("Stream Audio Mixer")
        self.resize(470, 500)
        self.setMinimumSize(420, 560)
        self.bot_process = None
        self.bot_log_handle = None
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)

        self.central = QWidget()
        self.central.setObjectName("centralWidget")
        self.setCentralWidget(self.central)

        self._setup_ui()
        self._setup_tray()
        self.setStyleSheet(AERO_QSS)

        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.poll_state)
        self.poll_timer.start(1500)

        self.drag_pos = None
        self.poll_state()

    # -- Tray icon setup --

    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.icon = create_aero_tray_icon()
        self.tray_icon.setIcon(self.icon)
        self.setWindowIcon(self.icon)
        self.tray_icon.setToolTip("Stream Audio Mixer (Frutiger Aero)")

        # Tray Context Menu
        tray_menu = QMenu()
        tray_menu.setStyleSheet("""
            QMenu {
                background: rgba(235, 245, 255, 245);
                border: 1px solid rgba(120, 180, 230, 180);
                border-radius: 6px;
                color: rgba(15, 60, 130, 230);
                font-family: "Segoe UI", "Ubuntu", sans-serif;
                font-size: 12px;
                padding: 4px;
            }
            QMenu::item:selected {
                background: rgba(180, 220, 250, 200);
                color: rgba(10, 45, 110, 255);
                border-radius: 4px;
            }
        """)

        show_action = QAction("Open / Restore", self)
        show_action.triggered.connect(self._restore_from_tray)
        tray_menu.addAction(show_action)

        hide_action = QAction("Minimize to Tray", self)
        hide_action.triggered.connect(self.hide)
        tray_menu.addAction(hide_action)

        tray_menu.addSeparator()

        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self._restore_from_tray()

    def _restore_from_tray(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _translate(self, key: str, **kwargs) -> str:
        strings = TRANSLATIONS.get(self.language_code, TRANSLATIONS["en"])
        value = strings.get(key, key)
        return value.format(**kwargs) if kwargs else value

    def _on_language_changed(self):
        code = self.language_combo.currentData() or "en"
        self.language_code = code
        save_language(code)
        self._apply_language()

    def _apply_language(self):
        self.setWindowTitle(self._translate("title"))
        self.status_label.setText(self._translate("status_checking"))
        self.device_label.setText(self._translate(
            "device_status", sink="?", source="?"))

        self.language_combo.blockSignals(True)
        self.language_combo.setCurrentIndex(
            list(LANGUAGE_OPTIONS.keys()).index(self.language_code)
        )
        self.language_combo.blockSignals(False)

        if hasattr(self, "stream_mode_combo"):
            selected = self.stream_mode_combo.currentData() or "desktop"
            self.stream_mode_combo.clear()
            self.stream_mode_combo.addItem(
                self._translate("desktop_only"), "desktop")
            self.stream_mode_combo.addItem(
                self._translate("mic_plus_desktop"), "mic")
            if selected in ("desktop", "mic"):
                self.stream_mode_combo.setCurrentIndex(
                    0 if selected == "desktop" else 1
                )
            else:
                self.stream_mode_combo.setCurrentIndex(0)

        if hasattr(self, "mode_label"):
            self.mode_label.setText(self._translate("source_mode"))
        if hasattr(self, "cl1"):
            self.cl1.setText(self._translate("desktop_audio"))
        if hasattr(self, "bl_label"):
            self.bl_label.setText(self._translate("filtered_apps"))
        if hasattr(self, "self.blocked_active_label"):
            self.blocked_active_label.setText(self._translate("none_running"))
        if hasattr(self, "self.bl_input"):
            self.bl_input.setPlaceholderText(
                self._translate("app_name_to_block"))
        if hasattr(self, "bot_label"):
            self.bot_label.setText(self._translate("discord_bot"))
        if hasattr(self, "self.bot_token_input"):
            self.bot_token_input.setPlaceholderText(
                self._translate("bot_token_placeholder"))
        if hasattr(self, "self.load_token_btn"):
            self.load_token_btn.setText(self._translate("load_token"))
        if hasattr(self, "self.save_token_btn"):
            self.save_token_btn.setText(self._translate("save_token"))
        if hasattr(self, "self.start_bot_btn"):
            self.start_bot_btn.setText(self._translate("start_bot"))
        if hasattr(self, "transmission_label"):
            transmission_label = getattr(self, "transmission_label", None)
            if transmission_label is not None:
                transmission_label.setText(self._translate("bot_volume"))
        if hasattr(self, "self.bot_status_label"):
            self.bot_status_label.setText(self._translate("bot_stopped"))
        if hasattr(self, "self.start_btn"):
            self.start_btn.setText(self._translate("start"))
        if hasattr(self, "self.teardown_btn"):
            self.teardown_btn.setText(self._translate("teardown"))
        if hasattr(self, "hint"):
            self.hint.setText(self._translate("drag_hint"))
        if hasattr(self, "language_label"):
            self.language_label.setText(self._translate("language"))

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
        self.hide()

    # -- UI construction --

    def _setup_ui(self):
        layout = QVBoxLayout(self.central)
        layout.setSpacing(10)
        layout.setContentsMargins(18, 16, 18, 16)

        title_row = QHBoxLayout()
        title = QLabel(self._translate("title"))
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignCenter)
        title_row.addWidget(title)
        title_row.addStretch()

        self.language_combo = QComboBox()
        self.language_combo.setFixedWidth(72)
        self.language_combo.setStyleSheet("""
            QComboBox {
                background: rgba(245, 250, 255, 220);
                border: 1px solid rgba(100, 160, 215, 150);
                border-radius: 5px;
                padding: 2px 6px;
                color: rgba(15, 55, 120, 230);
                font-size: 11px;
                font-weight: bold;
            }
            QComboBox::drop-down {
                width: 0px;
                border: none;
            }
        """)
        for code, label in LANGUAGE_OPTIONS.items():
            self.language_combo.addItem(label, code)
        self.language_combo.setCurrentIndex(
            list(LANGUAGE_OPTIONS.keys()).index(self.language_code)
        )
        self.language_combo.currentIndexChanged.connect(
            self._on_language_changed)
        title_row.addWidget(self.language_combo)
        layout.addLayout(title_row)

        self.status_label = QLabel(self._translate("status_checking"))
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        self.device_label = QLabel("")
        self.device_label.setObjectName("deviceLabel")
        self.device_label.setAlignment(Qt.AlignCenter)
        self.device_label.setWordWrap(True)
        layout.addWidget(self.device_label)

        mode_frame = QFrame()
        mode_frame.setObjectName("sectionCard")
        mode_layout = QVBoxLayout(mode_frame)
        mode_layout.setContentsMargins(12, 10, 12, 10)
        mode_row = QHBoxLayout()
        self.mode_label = QLabel(self._translate("source_mode"))
        self.mode_label.setObjectName("channelLabel")
        mode_row.addWidget(self.mode_label)
        self.stream_mode_combo = QComboBox()
        self.stream_mode_combo.addItem(
            self._translate("desktop_only"), "desktop")
        self.stream_mode_combo.addItem(
            self._translate("mic_plus_desktop"), "mic")
        self.stream_mode_combo.setCurrentIndex(0)
        mode_row.addWidget(self.stream_mode_combo)
        mode_layout.addLayout(mode_row)
        layout.addWidget(mode_frame)

        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        audio_frame = QFrame()
        audio_frame.setObjectName("sectionCard")
        audio_layout = QVBoxLayout(audio_frame)
        audio_layout.setContentsMargins(12, 10, 12, 10)

        self.cl1 = QLabel(self._translate("desktop_audio"))
        self.cl1.setObjectName("channelLabel")
        audio_layout.addWidget(self.cl1)

        self.desktop_slider = QSlider(Qt.Horizontal)
        self.desktop_slider.setRange(0, 200)
        self.desktop_slider.setValue(50)
        self.desktop_slider.valueChanged.connect(
            lambda v: self.desktop_vol_label.setText(f"{v}%"))
        self.desktop_slider.valueChanged.connect(
            self._on_desktop_slider_changed)
        audio_layout.addWidget(self.desktop_slider)

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
        audio_layout.addLayout(drow)

        layout.addWidget(audio_frame)

        sep2 = QFrame()
        sep2.setObjectName("separator")
        sep2.setFrameShape(QFrame.HLine)
        layout.addWidget(sep2)

        app_frame = QFrame()
        app_frame.setObjectName("sectionCard")
        app_layout = QVBoxLayout(app_frame)
        app_layout.setContentsMargins(12, 10, 12, 10)

        self.bl_label = QLabel(self._translate("filtered_apps"))
        self.bl_label.setMaximumHeight(20)
        self.bl_label.setObjectName("channelLabel")
        app_layout.addWidget(self.bl_label)

        # List of currently-blocked-active apps (live status)
        self.blocked_active_label = QLabel(self._translate("none_running"))
        self.blocked_active_label.setObjectName("deviceLabel")
        self.blocked_active_label.setWordWrap(True)
        app_layout.addWidget(self.blocked_active_label)

        self.blocklist_widget = QListWidget()
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
        self.blocklist_widget.setMaximumHeight(300)
        for entry in BLOCKED_APPS:
            self.blocklist_widget.addItem(QListWidgetItem(entry))
        app_layout.addWidget(self.blocklist_widget)

        add_row = QHBoxLayout()
        self.bl_input = QLineEdit()
        self.bl_input.setPlaceholderText(self._translate("app_name_to_block"))
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
        app_layout.addLayout(add_row)
        layout.addWidget(app_frame)

        bot_frame = QFrame()
        bot_frame.setObjectName("sectionCard")
        bot_layout = QVBoxLayout(bot_frame)
        bot_layout.setContentsMargins(12, 10, 12, 10)

        self.bot_label = QLabel(self._translate("discord_bot"))
        self.bot_label.setObjectName("channelLabel")
        bot_layout.addWidget(self.bot_label)

        self.bot_token_input = QLineEdit()
        self.bot_token_input.setPlaceholderText(
            self._translate("bot_token_placeholder"))
        self.bot_token_input.setEchoMode(QLineEdit.Password)
        self.bot_token_input.setStyleSheet("""
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
        """)
        bot_layout.addWidget(self.bot_token_input)

        bot_token_row = QHBoxLayout()
        bot_token_row.setSpacing(8)
        bot_token_row.setContentsMargins(0, 0, 0, 0)
        self.load_token_btn = QPushButton(self._translate("load_token"))
        self.load_token_btn.clicked.connect(self._on_load_token)
        self.save_token_btn = QPushButton(self._translate("save_token"))
        self.save_token_btn.clicked.connect(self._on_save_token)
        self.start_bot_btn = QPushButton(self._translate("start_bot"))
        self.start_bot_btn.clicked.connect(self._on_start_discord_bot)
        for button in (
            self.load_token_btn,
            self.save_token_btn,
            self.start_bot_btn,
        ):
            button.setObjectName("botActionButton")
            button.setMinimumHeight(30)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            bot_token_row.addWidget(button, 1)
        bot_layout.addLayout(bot_token_row)

        self.transmission_label = QLabel(self._translate("bot_volume"))
        self.transmission_label.setObjectName("channelLabel")
        bot_layout.addWidget(self.transmission_label)
        self.bot_volume_slider = QSlider(Qt.Horizontal)
        self.bot_volume_slider.setRange(0, 200)
        self.bot_volume_slider.setValue(100)
        self.bot_volume_slider.valueChanged.connect(
            lambda value: self.bot_volume_label.setText(f"{value}%"))
        self.bot_volume_slider.valueChanged.connect(save_bot_volume)
        bot_layout.addWidget(self.bot_volume_slider)
        self.bot_volume_label = QLabel("100%")
        self.bot_volume_label.setObjectName("volPct")
        bot_layout.addWidget(self.bot_volume_label)

        self.bot_status_label = QLabel(self._translate("bot_stopped"))
        self.bot_status_label.setObjectName("deviceLabel")
        bot_layout.addWidget(self.bot_status_label)
        layout.addWidget(bot_frame)

        # Separator before buttons
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton(self._translate("start"))
        self.start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self.start_btn)

        self.teardown_btn = QPushButton(self._translate("teardown"))
        self.teardown_btn.setObjectName("teardownBtn")
        self.teardown_btn.clicked.connect(self._on_teardown)
        btn_row.addWidget(self.teardown_btn)
        layout.addLayout(btn_row)

        # Close hint
        self.hint = QLabel(self._translate("drag_hint"))
        self.hint.setObjectName("deviceLabel")
        self.hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.hint)

        self._apply_language()

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
        self.status_label.setText(self._translate("setting_up"))
        source_mode = self.stream_mode_combo.currentData()
        success, msg = setup_mixer(source_mode=source_mode)
        self.status_label.setText(
            f"{'OK' if success else 'FAIL'}  {msg}" if not success else self._translate("running"))
        self.start_btn.setEnabled(True)
        self.poll_state()

    def _on_load_token(self):
        token = load_discord_token()
        if token:
            self.bot_token_input.setText(token)
            self.bot_status_label.setText(self._translate("token_loaded"))
        else:
            self.bot_status_label.setText(
                self._translate("no_token_saved"))

    def _on_save_token(self):
        token = self.bot_token_input.text().strip()
        if not token:
            self.bot_status_label.setText(self._translate("enter_token"))
            return
        save_discord_token(token)
        self.bot_status_label.setText(self._translate("token_saved"))

    def _on_start_discord_bot(self):
        token = self.bot_token_input.text().strip() or load_discord_token()
        if not token:
            self.bot_status_label.setText(
                self._translate("token_empty"))
            return

        self.start_btn.setEnabled(False)
        self.status_label.setText(self._translate("setting_up_mixer"))
        source_mode = self.stream_mode_combo.currentData()
        if has_null_sink():
            success, msg = True, "Mixer already running"
        else:
            success, msg = setup_mixer(source_mode=source_mode)
        if not success:
            self.status_label.setText(f"FAIL  {msg}")
            self.start_btn.setEnabled(True)
            return

        self.status_label.setText(self._translate("running"))
        self.start_btn.setEnabled(True)
        self.poll_state()

        try:
            if self.bot_process and self.bot_process.poll() is None:
                self.bot_status_label.setText(
                    self._translate("bot_already_running"))
                return

            project_dir = os.path.dirname(os.path.abspath(__file__))
            venv_python = os.path.join(project_dir, ".venv", "bin", "python")
            bot_python = venv_python if os.path.isfile(
                venv_python) else sys.executable
            bot_env = os.environ.copy()
            bot_env["DISCORD_BOT_TOKEN"] = token
            save_bot_volume(self.bot_volume_slider.value())
            self.bot_log_handle = open(BOT_LOG_FILE, "a", encoding="utf-8")
            self.bot_process = subprocess.Popen(
                get_bot_command(project_dir, bot_python),
                stdout=self.bot_log_handle,
                stderr=subprocess.STDOUT,
                env=bot_env,
                start_new_session=True,
                preexec_fn=_terminate_bot_with_parent,
            )
            self.bot_status_label.setText(
                self._translate("bot_starting", pid=self.bot_process.pid))
        except Exception as exc:
            if self.bot_log_handle:
                self.bot_log_handle.close()
                self.bot_log_handle = None
            self.bot_process = None
            self.bot_status_label.setText(
                self._translate("error_starting_bot", exc=exc))

    def _close_bot_log(self):
        if self.bot_log_handle:
            self.bot_log_handle.close()
            self.bot_log_handle = None

    def _stop_discord_bot(self):
        if not self.bot_process or self.bot_process.poll() is not None:
            self.bot_process = None
            return

        try:
            os.killpg(self.bot_process.pid, 15)
            self.bot_process.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            if self.bot_process.poll() is None:
                os.killpg(self.bot_process.pid, 9)
                self.bot_process.wait(timeout=2)
        finally:
            self._close_bot_log()
            self.bot_process = None
            self.bot_status_label.setText(self._translate("bot_stopped"))

    def _on_teardown(self):
        self.teardown_btn.setEnabled(False)
        self.status_label.setText("Tearing down...")
        self._stop_discord_bot()
        teardown_mixer()
        self.status_label.setText("Stopped")
        self.teardown_btn.setEnabled(True)
        self.poll_state()

    def closeEvent(self, event):
        self._stop_discord_bot()
        teardown_mixer()
        self.tray_icon.hide()
        event.accept()

    def _on_desktop_slider_changed(self, value):
        state = get_mixer_state()
        inputs = get_desktop_stream_inputs(state["mic_mod"])
        set_stream_inputs_volume(inputs, value)

    def _on_desktop_mute_toggled(self):
        state = get_mixer_state()
        inputs = get_desktop_stream_inputs(state["mic_mod"])
        set_stream_inputs_mute(inputs, self.desktop_mute_btn.isChecked())

    # -- polling --

    def poll_state(self):
        if self.bot_process and self.bot_process.poll() is not None:
            exit_code = self.bot_process.returncode
            self._close_bot_log()
            self.bot_process = None
            self.bot_status_label.setText(
                self._translate("bot_stopped_exit", code=exit_code))

        state = get_mixer_state()

        # Enforce blocklist on every poll tick
        if state["active"]:
            enforce_blocklist()

        if state["active"]:
            self.status_label.setText(self._translate("running"))
            self.start_btn.setEnabled(False)
            self.teardown_btn.setEnabled(True)
            self.desktop_slider.setEnabled(True)
            self.desktop_mute_btn.setEnabled(True)
        else:
            self.status_label.setText(self._translate("stopped"))
            self.start_btn.setEnabled(True)
            self.teardown_btn.setEnabled(False)
            self.desktop_slider.setEnabled(False)
            self.desktop_mute_btn.setEnabled(False)

        # Device info
        sn = state["default_sink"] or "?"
        sc = state["default_source"] or "?"
        self.device_label.setText(
            self._translate("device_status", sink=sn[:50], source=sc[:50])
        )

        # Blocked apps — live status
        blocked = state["blocked_active"]
        if blocked:
            self.blocked_active_label.setText(
                self._translate("blocked_now", apps=", ".join(blocked)))
        elif state["active"]:
            self.blocked_active_label.setText(
                self._translate("no_blocked_apps"))
        else:
            self.blocked_active_label.setText("")

        # Update sliders from actual state (block signals to avoid feedback)
        self.desktop_slider.blockSignals(True)
        self.desktop_slider.setValue(state["desktop_vol"])
        self.desktop_slider.blockSignals(False)
        self.desktop_vol_label.setText(f"{state['desktop_vol']}%")

        self.desktop_mute_btn.blockSignals(True)
        self.desktop_mute_btn.setChecked(state["desktop_muted"])
        self.desktop_mute_btn.blockSignals(False)


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
