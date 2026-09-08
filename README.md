# AeroStream Mixer 🌊🎛️

Frutiger Aero styled PipeWire audio router for Linux. Mixes desktop sound and microphone into a single virtual stream source while isolating apps like Discord so call participants don't hear themselves.

---

## 🚀 Why Use This?

- **Linux Screenshare Audio Bypass:** If your Discord or browser screenshare on Linux can't stream application audio, select `stream-mix.monitor` as your input device to stream both your mic and your game/system audio at the same time.
- **App Isolation:** Automatically prevents Discord/Zoom/Teams from being sent to the stream while keeping them fully audible in your headphones.

---

## 🛠️ Requirements & Test Conditions

> **Note:** Developed and tested specifically on **Linux Mint 22.2 (XFCE)** using **PipeWire 1.0.5** with ALSA (`k7.0.0-30-generic`, `snd_hda_intel` / `snd-usb-audio`).

```bash
sudo apt update && sudo apt install -y python3 python3-pyqt5 pulseaudio-utils
```

---

## 📦 Quick Start

```bash
git clone https://github.com/nickolasrm/AeroStream-Mixer.git
cd AeroStream-Mixer
python3 stream-audio-mixer.py
```

1. Click **Start** in the GUI.
2. In Discord / OBS / browser, set your **Microphone / Input Device** to:
   ```text
   Stream audio mix (desktop + mic) [stream-mix.monitor]
   ```
3. Add any app name to **Filtered Apps** to exclude it from the stream passthrough.
4. Click **Teardown** when done.

---

## 💻 CLI Usage (Optional)

```bash
./setup-stream-audio.sh              # Start mixer
./set-stream-volume.sh desktop 0.6   # Desktop volume (0.0 - 1.0)
./set-stream-volume.sh mic 0.8       # Mic volume (0.0 - 1.0)
./teardown-stream-audio.sh           # Stop and clean up
```

---

## 📄 License

MIT
