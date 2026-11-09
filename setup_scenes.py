#!/usr/bin/env python3
"""
Setup Audio (HyperX QuadCast) and Camera (Rog Camera) on all monitor scenes.
Positions the webcam in the bottom-right corner of the 2560x1600 canvas.
"""
import asyncio
import json
import os
import websockets

OBS_WS_URL = os.environ.get("OBS_WS_URL", "ws://127.0.0.1:4455")
MIC_SOURCE_NAME = "Audio Input Capture (PulseAudio)"  # HyperX QuadCast S
CAMERA_SOURCE_NAME = "Rog Camera"                    # Laptop FHD WebCam

DESKTOP_AUDIO_SOURCE_NAME = "Audio Output Capture (PulseAudio)"

TARGET_SCENES = [
    "Scena-eDP-1",
    "Scena-HDMI-A-1",
    "Scena-DP-7",
    "Scena-DP-6",
    "Scena-DP-3"
]

# Canvas: 2560x1600
# Camera box: 560x315 (16:9)
# Margins: 30px right, 30px bottom
CAM_WIDTH = 560.0
CAM_HEIGHT = 315.0
CAM_POS_X = 2560.0 - CAM_WIDTH - 30.0   # 1970.0
CAM_POS_Y = 1600.0 - CAM_HEIGHT - 30.0  # 1255.0

async def send_request(ws, req_type, req_data):
    req_id = f"req_{req_type}_{os.urandom(4).hex()}"
    await ws.send(json.dumps({
        "op": 6,
        "d": {
            "requestType": req_type,
            "requestId": req_id,
            "requestData": req_data
        }
    }))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("op") == 7 and msg.get("d", {}).get("requestId") == req_id:
            return msg["d"]

async def main():
    print(f"Łączenie z OBS na {OBS_WS_URL}...")
    async with websockets.connect(OBS_WS_URL) as ws:
        await ws.recv() # Hello (op:0)
        await ws.send(json.dumps({"op": 1, "d": {"rpcVersion": 1, "eventSubscriptions": 0}}))
        await ws.recv() # Identified (op:2)
        print("✅ Zidentyfikowano w OBS!")

        # 1. Konfiguracja podkładu dźwiękowego (Dźwięk pulpitu / głośniki)
        print("\n🎵 Konfiguracja podkładu audio (Dźwięk pulpitu)...")
        # Ustaw domyślne wyjście (PipeWire default sink)
        await send_request(ws, "SetInputSettings", {
            "inputName": DESKTOP_AUDIO_SOURCE_NAME,
            "inputSettings": {"device_id": "default"}
        })
        # Wycisz bazowo podkład do -22 dB (subtelne tło)
        await send_request(ws, "SetInputVolume", {
            "inputName": DESKTOP_AUDIO_SOURCE_NAME,
            "inputVolumeDb": -22.0
        })
        print("  🔉 Ustawiono głośność podkładu na -22 dB (subtelne tło)")

        # Dodaj filtr Ducking (automatyczne wyciszanie muzyki głosem z mikrofonu)
        flist = await send_request(ws, "GetSourceFilterList", {"sourceName": DESKTOP_AUDIO_SOURCE_NAME})
        filters = [f["filterName"] for f in flist.get("responseData", {}).get("filters", [])]
        if "Auto-Ducking (Wyciszanie mową)" not in filters:
            await send_request(ws, "CreateSourceFilter", {
                "sourceName": DESKTOP_AUDIO_SOURCE_NAME,
                "filterName": "Auto-Ducking (Wyciszanie mową)",
                "filterKind": "compressor_filter",
                "filterSettings": {
                    "ratio": 4.0,
                    "threshold": -32.0,
                    "attack_time": 25,
                    "release_time": 600,
                    "output_gain": 0.0,
                    "sidechain_source": MIC_SOURCE_NAME
                }
            })
            print(f"  🎙️ Dodano filtr Auto-Ducking (Sidechain z: '{MIC_SOURCE_NAME}')")
        else:
            print("  🎙️ Filtr Auto-Ducking już istnieje")

        # 2. Konfiguracja w scenach
        for scene_name in TARGET_SCENES:
            print(f"\n⚙️  Konfiguracja sceny: {scene_name}")
            
            # Pobierz istniejące elementy w scenie
            list_res = await send_request(ws, "GetSceneItemList", {"sceneName": scene_name})
            items = list_res.get("responseData", {}).get("sceneItems", [])
            existing_sources = {it["sourceName"]: it["sceneItemId"] for it in items}

            # Dodaj Mikrofon HyperX, jeśli go nie ma
            if MIC_SOURCE_NAME not in existing_sources:
                await send_request(ws, "CreateSceneItem", {
                    "sceneName": scene_name,
                    "sourceName": MIC_SOURCE_NAME,
                    "sceneItemEnabled": True
                })
                print(f"  🎤 Dodano mikrofon: '{MIC_SOURCE_NAME}'")
            else:
                print(f"  🎤 Mikrofon już istnieje w scenie")

            # Dodaj Dźwięk pulpitu / muzykę, jeśli jej nie ma
            if DESKTOP_AUDIO_SOURCE_NAME not in existing_sources:
                await send_request(ws, "CreateSceneItem", {
                    "sceneName": scene_name,
                    "sourceName": DESKTOP_AUDIO_SOURCE_NAME,
                    "sceneItemEnabled": True
                })
                print(f"  🎵 Dodano podkład audio: '{DESKTOP_AUDIO_SOURCE_NAME}'")
            else:
                print(f"  🎵 Podkład audio już istnieje w scenie")

            # Dodaj Kamerkę z laptopa (Rog Camera)
            cam_item_id = existing_sources.get(CAMERA_SOURCE_NAME)
            if not cam_item_id:
                add_cam_res = await send_request(ws, "CreateSceneItem", {
                    "sceneName": scene_name,
                    "sourceName": CAMERA_SOURCE_NAME,
                    "sceneItemEnabled": True
                })
                cam_item_id = add_cam_res.get("responseData", {}).get("sceneItemId")
                print(f"  📷 Dodano kamerkę: '{CAMERA_SOURCE_NAME}' (ID: {cam_item_id})")
            else:
                print(f"  📷 Kamerka już istnieje w scenie (ID: {cam_item_id})")

            # Ustaw pozycję kamerki: prawy dolny róg
            if cam_item_id:
                await send_request(ws, "SetSceneItemTransform", {
                    "sceneName": scene_name,
                    "sceneItemId": cam_item_id,
                    "sceneItemTransform": {
                        "boundsType": "OBS_BOUNDS_SCALE_INNER",
                        "boundsWidth": CAM_WIDTH,
                        "boundsHeight": CAM_HEIGHT,
                        "positionX": CAM_POS_X,
                        "positionY": CAM_POS_Y,
                        "alignment": 5 # Top-Left
                    }
                })
                print(f"  📐 Ustawiono kadr kamerki w prawym dolnym rogu (X: {CAM_POS_X}, Y: {CAM_POS_Y}, rozmiar: {CAM_WIDTH}x{CAM_HEIGHT})")

        print("\n🎉 Sukces! Mikrofon, podkład muzyczny z duckingiem i kamerka są w pełni skonfigurowane.")

if __name__ == "__main__":
    asyncio.run(main())
