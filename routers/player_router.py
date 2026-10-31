"""
Scenario Player Endpoints
Controls playback of vehicle crash and driving scenarios over MQTT.
"""

import math
import os
from fastapi import APIRouter, HTTPException

from core.config import SCENARIOS_DIR
from core.models import PlayRequest, StepRequest
from core.player import load_scenario_chunks, player

router = APIRouter(tags=["Player"])


@router.get("/api/scenarios")
def list_scenarios():
    """Returns metadata for all available JSON scenarios in scenarios/ folder."""
    result = []
    if not os.path.exists(SCENARIOS_DIR):
        return result

    for fname in sorted(os.listdir(SCENARIOS_DIR)):
        if fname.endswith(".json"):
            fpath = os.path.join(SCENARIOS_DIR, fname)
            try:
                chunks = load_scenario_chunks(fpath)
                speeds = [c.get("gps_speed_kmh") for c in chunks if c.get("gps_speed_kmh") is not None]
                mags = []
                for c in chunks:
                    for x, y, z in c.get("acc", []):
                        mags.append(math.sqrt(x * x + y * y + z * z))

                clean_name = fname.replace(".json", "").replace("_", " ").title()
                category = "crash" if "crash" in fname and "no_crash" not in fname else ("jolt" if "trigger" in fname else "normal")
                description = (
                    "High-G collision event with severe deceleration; triggers remote M2 classifier."
                    if category == "crash"
                    else (
                        "Sudden jolt / pothole (>1g trigger) that correctly resolves to non-crash."
                        if category == "jolt"
                        else "Baseline smooth vehicle driving with nominal road vibration."
                    )
                )

                result.append({
                    "filename": fname,
                    "name": clean_name,
                    "category": category,
                    "description": description,
                    "total_seconds": len(chunks),
                    "total_samples": len(mags),
                    "peak_g": round(max(mags), 2) if mags else 1.0,
                    "min_speed": round(min(speeds), 1) if speeds else 0.0,
                    "max_speed": round(max(speeds), 1) if speeds else 0.0,
                })
            except Exception as e:
                print(f"[Error reading scenario {fname}] {e}")

    return result


@router.post("/api/player/start")
async def start_scenario(req: PlayRequest):
    """Start playing a scenario over MQTT."""
    try:
        player.start(
            filename=req.scenario,
            loop=req.loop,
            speed_multiplier=req.speed_multiplier,
            device_id=req.device_id,
            lead_in=req.lead_in_normal,
        )
        return {"status": "started", "player": player.status()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/player/pause")
async def pause_scenario():
    """Pause playback."""
    player.pause()
    return {"status": "paused", "player": player.status()}


@router.post("/api/player/resume")
async def resume_scenario():
    """Resume playback."""
    player.resume()
    return {"status": "resumed", "player": player.status()}


@router.post("/api/player/stop")
async def stop_scenario():
    """Stop playback and reset to start."""
    player.stop()
    return {"status": "stopped", "player": player.status()}


@router.post("/api/player/step")
async def step_scenario(req: StepRequest):
    """Step forward exactly 1 second in the scenario."""
    try:
        if player.current_scenario != req.scenario or player.lead_in_normal != req.lead_in_normal:
            player.load_scenario(req.scenario, lead_in=req.lead_in_normal)
        player.device_id = req.device_id
        msg = player.send_step()
        return {"status": "stepped", "message": msg, "player": player.status()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/player/status")
def get_player_status():
    """Get player state."""
    return player.status()
