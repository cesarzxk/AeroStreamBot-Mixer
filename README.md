# AeroStream Mixer (AeroAudioMixer) 🌊🎛️

> **A Frutiger Aero style desktop audio router and streamer companion for Linux.**  
> Mix desktop audio and microphone inputs into a unified virtual stream channel with real-time app isolation (e.g. Discord loopback prevention).

---

## ✨ Overview

Many Linux streaming/screensharing apps (such as Discord on Linux, custom WebRTC clients, OBS, and browser screen share sessions) struggle with sharing internal audio or combining separate microphone and desktop sound without messy setups or painful echo loops.

**AeroStream Mixer** provides a clean GUI and CLI scripts to:
1. Combine desktop sound and your microphone into a single virtual monitor channel (`stream-mix.monitor`).
2. **Filter & isolate specific apps (like Discord, Zoom, Teams)** so that call participants do not hear themselves echoed back through your stream/screenshare, while you continue to hear them normally in your own speakers/headphones.
3. Allow Linux users without native application-audio screenshare support to use their microphone or monitor device to broadcast crystal clear game/system sound alongside their voice.
4. Present a nostalgic **Frutiger Aero / Windows Vista & 7** glass aesthetic built with PyQt5.

---

## 🎧 The Linux Screenshare & Audio Echo Problem Solved

### The Problem
- When screensharing on Linux, capturing desktop sound often forces you to share the entire master audio sink.
- If you are in a voice call on Discord, your friends' voices are picked up by the desktop monitor loopback and sent back into the call, creating a disorienting echo.
- Furthermore, apps that lack per-window audio capture leave Linux users unable to stream gameplay audio alongside microphone commentary.

### The AeroStream Solution
```
[ Discord / Call App ] ──► [ stream-block Sink ] ──► (loopback) ──► [ Your Speakers/Headphones ] (Audible to you)
                                      ↛ (blocked from stream)

[ Games / Music / System ] ────────► [ Default Sink ] ────► (loopback) ──► [ stream-mix Sink ] ──► Stream / Screenshare
[ Microphone ] ───────────────────────────────────────────► (loopback) ──► [ stream-mix.monitor ]
```

- **You hear everything:** Both game audio and your voice chat call.
- **Your stream hears:** Game audio + your voice.
- **Your friends hear:** Just your voice and the game (no self-echo!).

---

## 🖥️ System & Hardware Environment Tested

This project was built and validated under the following exact environment:

- **OS / Distribution:** Linux Mint 22.2 (*Zara*) 64-bit
- **Desktop Environment:** XFCE 4.18
- **Audio Server / Driver:** PipeWire `1.0.5` with ALSA kernel API (`k7.0.0-30-generic`) & `pactl` (PulseAudio emulation layer)
- **Tested Audio Hardware:** 
  - NVIDIA GA104 / AMD Starship/Matisse HD Audio (`snd_hda_intel`)
  - Fifine USB Microphone (`snd-usb-audio`)

*Note: Any modern Linux distribution running PipeWire with `pipewire-pulse` and `pulseaudio-utils` (`pactl`) should work seamlessly.*

---

## 🚀 Installation & Requirements

### Prerequisites
Make sure Python 3, PyQt5, and `pactl` are installed:

```bash
# Ubuntu / Linux Mint / Debian
sudo apt update
sudo apt install python3 python3-pyqt5 pulseaudio-utils
```

### Clone the Repository
```bash
git clone https://github.com/<YOUR_USERNAME>/AeroStream-Mixer.git
cd AeroStream-Mixer
chmod +x *.sh stream-audio-mixer.py
```

---

## 📖 Usage Guide

### 1. Launching the Frutiger Aero GUI
```bash
python3 stream-audio-mixer.py
```
- Click **Start** to initialize virtual sinks and loopback routing.
- Adjust **Desktop Audio** and **Microphone** sliders to balance sound levels in real-time.
- Manage **Filtered Apps**: type `discord`, `zoom`, `teams`, or any application binary name and press `+` to isolate it from the stream channel.
- Click **Teardown** when finished to cleanly remove virtual sinks.

### 2. Configuring Discord / OBS / Streaming Software
1. In your streaming app (OBS, Discord, WebRTC browser, etc.), set your **Audio Input / Microphone** device to:
   ```
   Stream audio mix (desktop + mic) [stream-mix.monitor]
   ```
2. For screensharing: Linux users who cannot screenshare with audio can select `stream-mix.monitor` as their stream voice/mic source to broadcast both game audio and mic simultaneously!

### 3. Headless / CLI Control (Optional)
If you prefer running via terminal without the GUI:
```bash
# Start stream routing
./setup-stream-audio.sh

# Adjust volume levels (0.0 - 1.0)
./set-stream-volume.sh desktop 0.6
./set-stream-volume.sh mic 0.8
./set-stream-volume.sh mic mute
./set-stream-volume.sh mic unmute

# Teardown routing
./teardown-stream-audio.sh
```

---

## 📁 Repository Structure

```
AeroStream-Mixer/
├── stream-audio-mixer.py     # Main Frutiger Aero GUI application (PyQt5)
├── setup-stream-audio.sh     # Shell script to establish PipeWire virtual routing
├── set-stream-volume.sh      # CLI utility for adjusting per-channel loopback volume
├── teardown-stream-audio.sh  # Script to cleanly tear down sinks & loopbacks
└── README.md                 # Documentation
```

---

## 📄 License
MIT License. Feel free to use, modify, and distribute.
