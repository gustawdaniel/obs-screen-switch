#!/usr/bin/env python3
"""
Hyprland Safe Stream / Privacy Scene Switcher for OBS.

Rules:
- eDP-1 (Środkowy laptop 2560x1600)  -> Przełącz na 'Scena-eDP-1'
- HDMI-A-1 lub DP-7 (Dwa lewe ekrany) -> Przełącz na 'Scena-Lewe-Dual' (oba ekrany obok siebie)
- DP-6 (Prawy ekran - prywatny)      -> IGNORUJ (OBS zostaje na obecnej scenie, brak wycieku haseł/kart)
- DP-3 (Dolny ekran ScreenPad)       -> IGNORUJ (OBS zostaje na obecnej scenie)
"""
import asyncio
import base64
import hashlib
import json
import os
import websockets

OBS_WS_URL = os.environ.get("OBS_WS_URL", "ws://127.0.0.1:4455")
OBS_WS_PASSWORD = os.environ.get("OBS_WS_PASSWORD", "")

# Bezpieczne mapowanie monitorów na sceny:
# DP-6 (prawy prywatny) oraz DP-3 (dolny) NIE występują w mapie -> są ignorowane!
SAFE_MONITOR_SCENE_MAP = {
    "eDP-1": "Scena-eDP-1",          # Główny ekran laptopa (16:10)
    "HDMI-A-1": "Scena-Lewe-Dual",   # Skrajnie lewy pionowy
    "DP-7": "Scena-Lewe-Dual",       # Środkowo-lewy pionowy
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
        "eventSubscriptions": 0
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
    print("🔒 [Safe Stream] Łączenie z OBS WebSocket...")
    async for ws in websockets.connect(OBS_WS_URL):
        receiver_task = None
        pending_switch = None
        try:
            await obs_identify(ws)
            print("🛡️  [Safe Stream] Aktywny tryb prywatności!")
            print("   👉 eDP-1          -> Scena-eDP-1")
            print("   👉 HDMI-A-1, DP-7 -> Scena-Lewe-Dual")
            print("   🛑 DP-6 (Prawy)   -> ZIGNOROWANY (bezpieczny)")
            print("   🛑 DP-3 (Dolny)   -> ZIGNOROWANY")

            async def drain_ws():
                try:
                    async for _ in ws:
                        pass
                except Exception:
                    pass

            receiver_task = asyncio.create_task(drain_ws())

            current_target_scene = None

            async def switch_scene(target_scene):
                nonlocal current_target_scene
                if target_scene == current_target_scene:
                    return
                req = {
                    "op": 6,
                    "d": {
                        "requestType": "SetCurrentProgramScene",
                        "requestId": f"switch-{target_scene}",
                        "requestData": {"sceneName": target_scene}
                    }
                }
                await ws.send(json.dumps(req))
                current_target_scene = target_scene
                print(f"🎬 OBS: przełączono na '{target_scene}'")

            # Początkowa synchronizacja
            try:
                proc = await asyncio.create_subprocess_exec(
                    "hyprctl", "monitors", "-j",
                    stdout=asyncio.subprocess.PIPE
                )
                stdout, _ = await proc.communicate()
                mons = json.loads(stdout.decode())
                for m in mons:
                    if m.get("focused"):
                        active_mon = m.get("name")
                        target = SAFE_MONITOR_SCENE_MAP.get(active_mon, "Scena-eDP-1")
                        await switch_scene(target)
                        break
            except Exception as e:
                print("Uwaga przy pobieraniu początkowego monitora:", e)

            # Nasłuchiwanie zdarzeń z Hyprlanda
            async for event in hyprland_events():
                if event.startswith("focusedmon>>"):
                    payload = event[len("focusedmon>>"):]
                    mon_name = payload.split(",")[0].strip()

                    # Jeśli wjechaliśmy na prawy monitor (DP-6) lub dolny (DP-3) -> IGNORUJEMY!
                    if mon_name not in SAFE_MONITOR_SCENE_MAP:
                        # Monitor prywatny/zignorowany - nie ruszamy sceny w OBS!
                        continue

                    target_scene = SAFE_MONITOR_SCENE_MAP[mon_name]

                    # Przełącz tylko wtedy, gdy celowa scena jest inna niż obecna
                    if target_scene != current_target_scene:
                        if pending_switch and not pending_switch.done():
                            pending_switch.cancel()

                        async def delayed_switch(target=target_scene):
                            try:
                                await asyncio.sleep(0.12)  # Histereza 120ms
                                await switch_scene(target)
                            except asyncio.CancelledError:
                                pass
                            except Exception as err:
                                print(f"Błąd przełączania: {err}")

                        pending_switch = asyncio.create_task(delayed_switch())

        except (websockets.ConnectionClosed, ConnectionRefusedError) as e:
            print(f"⚠️ Utracono połączenie z OBS ({e}). Ponowna próba za 3 sekundy...")
            if pending_switch and not pending_switch.done():
                pending_switch.cancel()
            if receiver_task and not receiver_task.done():
                receiver_task.cancel()
            await asyncio.sleep(3)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nZatrzymano Safe Switcher.")
