import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.events import bus

router = APIRouter(tags=["events"])


@router.get("/events")
def list_events(limit: int = 200) -> dict:
    return {"events": bus.recent(max(1, min(limit, 1000))), "live": False}


@router.websocket("/ws/events")
async def stream(ws: WebSocket) -> None:
    """Sends stored backlog once (live=false), then pushes new events as they are published (live=true)."""
    await ws.accept()
    backlog = bus.recent(100)
    last = backlog[-1]["id"] if backlog else 0
    try:
        await ws.send_json({"type": "backlog", "live": False, "events": backlog})
        while True:
            await asyncio.sleep(0.3)
            new = bus.since(last)
            if new:
                last = new[-1]["id"]
                await ws.send_json({"type": "events", "live": True, "events": new})
    except (WebSocketDisconnect, RuntimeError):
        return
