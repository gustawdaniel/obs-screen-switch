# 🎬 OBS Screen Switcher

Hyprland Monitor Focus to OBS Studio Scene Switcher.
Automatically detects when focus shifts across monitors in the Hyprland Wayland compositor via `socket2` and switches OBS Studio scenes in real-time over WebSocket (`obs-websocket` v5).

---

## 🚀 Features

- **Hyprland Event Driven:** Listens to `focusedmon` events directly from Hyprland IPC socket.
- **WebSocket v5 Protocol:** Communicates natively with OBS Studio 28+ built-in WebSocket server.
- **Fail-safe Reconnection:** Automatically reconnects if OBS Studio restarts or compositor socket reloads.
- **Customizable Monitor Map:** Easy mapping of display outputs (`eDP-1`, `DP-1`, `HDMI-A-1`) to OBS scene names.

---

## 📦 Installation & Requirements

Ensure you have Python 3.10+ and the required packages:

```bash
pip install websockets
```

Make sure **obs-websocket** is enabled in OBS Studio (`Tools` -> `WebSocket Server Settings`).

---

## ⚙️ Configuration

Set the environment variables if using custom ports or passwords:

```bash
export OBS_WS_URL="ws://127.0.0.1:4455"
export OBS_WS_PASSWORD="your-strong-password"
```

Map your display names to OBS scenes in `main.py` or `safe_main.py`:

```python
MONITOR_SCENE_MAP = {
    "eDP-1": "Scene-Laptop",
    "DP-1": "Scene-Primary",
    "HDMI-A-1": "Scene-External",
}
```

---

## 🏃 Running

```bash
python3 main.py
```

Or run the safe variant with rate limiting and debounce protection:

```bash
python3 safe_main.py
```

---

## 📄 License

This tool is part of the Brain OS ecosystem and is licensed under the [AGPL-3.0 License](LICENSE).
