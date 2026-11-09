#!/usr/bin/env python3
"""
Hyprland Monitor Focus to OBS Scene Switcher
Listens to Hyprland's socket2 and switches OBS scene to the active monitor.
"""
import asyncio
import base64
import hashlib
import json
import os
import websockets

OBS_WS_URL = os.environ.get("OBS_WS_URL", "ws://127.0.0.1:4455")
OBS_WS_PASSWORD = os.environ.get("OBS_WS_PASSWORD", "")

# Mapowanie nazw monitorów z Hyprlanda na nazwy scen w OBS
MONITOR_SCENE_MAP = {
    "eDP-1": "Scena-eDP-1",         # Laptop 2560x1600 (16:10)
    "HDMI-A-1": "Scena-HDMI-A-1",   # Lewy pionowy
    "DP-7": "Scena-DP-7",           # Środkowo-lewy pionowy
    "DP-6": "Scena-DP-6",           # Prawy pionowy
    "DP-3": "Scena-DP-3",           # Dolny ScreenPad
}

async def hyprland_events():
    his = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    xdg = os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000")
    sock_path = f"{xdg}/hypr/{his}/.socket2.sock"

    reader, _ = await asyncio.open_unix_connection(sock_path)
    while True:
        line = await reader.readline()
        if not line:
            break
        yield line.decode("utf-8", errors="ignore").strip()

async def obs_identify(ws):
    """OBS WebSocket v5 Handshake (Hello op:0 -> Identify op:1 -> Identified op:2)."""
    raw_hello = await ws.recv()
    hello = json.loads(raw_hello)
    if hello.get("op") != 0:
        raise RuntimeError(f"Oczekiwano Hello (op:0), otrzymano: {hello}")

    d = hello.get("d", {})
    auth_info = d.get("authentication")
    identify_data = {
        "rpcVersion": 1,
        "eventSubscriptions": 0  # Tylko wysyłamy komendy, nie subskrybujemy zbędnych zdarzeń
    }

    if auth_info:
        pw = OBS_WS_PASSWORD
        if not pw:
            raise RuntimeError("OBS WebSocket wymaga hasła! Ustaw zmienną środowiskową OBS_WS_PASSWORD.")
        secret_hash = hashlib.sha256((pw + auth_info["salt"]).encode("utf-8")).digest()
        secret_b64 = base64.b64encode(secret_hash).decode("utf-8")
        auth_resp = hashlib.sha256((secret_b64 + auth_info["challenge"]).encode("utf-8")).digest()
        identify_data["authentication"] = base64.b64encode(auth_resp).decode("utf-8")

    await ws.send(json.dumps({"op": 1, "d": identify_data}))
    raw_identified = await ws.recv()
    identified = json.loads(raw_identified)
    if identified.get("op") != 2:
        raise RuntimeError(f"Błąd identyfikacji OBS WebSocket: {identified}")

async def main():
    print("Łączenie z OBS WebSocket...")
    async for ws in websockets.connect(OBS_WS_URL):
        receiver_task = None
        pending_switch = None
        try:
            # 1. Autoryzacja i handshake protokołu OBS v5
            await obs_identify(ws)
            print("✅ Połączono i zidentyfikowano w OBS! Nasłuchiwanie ruchu myszy w Hyprlandzie...")

            # Odbiornik odpowiedzi OBS w tle
            async def drain_ws():
                try:
                    async for _ in ws:
                        pass
                except Exception:
                    pass

            receiver_task = asyncio.create_task(drain_ws())

            async def switch_scene(mon_name):
                scene_name = MONITOR_SCENE_MAP.get(mon_name)
                if not scene_name:
                    return
                req = {
                    "op": 6,  # Request
                    "d": {
                        "requestType": "SetCurrentProgramScene",
                        "requestId": f"switch-{mon_name}",
                        "requestData": {"sceneName": scene_name}
                    }
                }
                await ws.send(json.dumps(req))
                print(f"🎬 OBS: przełączono na '{scene_name}' (Monitor: {mon_name})")

            # 2. Natychmiastowa synchronizacja z aktualnie aktywnym monitorem
            current_monitor = None
            try:
                proc = await asyncio.create_subprocess_exec(
                    "hyprctl", "monitors", "-j",
                    stdout=asyncio.subprocess.PIPE
                )
                stdout, _ = await proc.communicate()
                mons = json.loads(stdout.decode())
                for m in mons:
                    if m.get("focused"):
                        current_monitor = m.get("name")
                        await switch_scene(current_monitor)
                        break
            except Exception as e:
                print("Uwaga przy pobieraniu początkowego monitora:", e)

            # 3. Pętla zdarzeń z Hyprlanda
            async for event in hyprland_events():
                if event.startswith("focusedmon>>"):
                    payload = event[len("focusedmon>>"):]
                    mon_name = payload.split(",")[0].strip()

                    if mon_name != current_monitor and mon_name in MONITOR_SCENE_MAP:
                        current_monitor = mon_name

                        if pending_switch and not pending_switch.done():
                            pending_switch.cancel()

                        async def delayed_switch(m=mon_name):
                            try:
                                await asyncio.sleep(0.12)  # Histereza 120ms
                                await switch_scene(m)
                            except asyncio.CancelledError:
                                pass
                            except Exception as err:
                                print(f"Błąd przełączania: {err}")

                        pending_switch = asyncio.create_task(delayed_switch())

        except (websockets.ConnectionClosed, ConnectionRefusedError) as e:
            print(f"⚠️ Połączenie z OBS zostało przerwane ({e}). Ponowna próba za 3 sekundy...")
            if pending_switch and not pending_switch.done():
                pending_switch.cancel()
            if receiver_task and not receiver_task.done():
                receiver_task.cancel()
            await asyncio.sleep(3)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nZatrzymano skrypt.")
