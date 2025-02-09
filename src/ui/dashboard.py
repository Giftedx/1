import os
import logging
import asyncio
import psutil
import aiohttp
from fastapi import FastAPI, WebSocket, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from src.metrics import ACTIVE_STREAMS, STREAM_QUALITY
from src.core.metrics_manager import MetricsManager
from src.core.tautulli_client import TautulliClient

logger = logging.getLogger(__name__)
app = FastAPI()
templates = Jinja2Templates(directory="src/ui/templates")

app.mount("/static", StaticFiles(directory="src/ui/static"), name="static")
metrics_manager = MetricsManager()

# Initialize Tautulli client
tautulli = TautulliClient(
    base_url=os.getenv('TAUTULLI_URL', 'http://localhost:8181'),
    api_key=os.getenv('TAUTULLI_API_KEY')
)

async def get_network_usage():
    net_io = psutil.net_io_counters()
    return {
        "bytes_sent": net_io.bytes_sent,
        "bytes_recv": net_io.bytes_recv,
        "packets_sent": net_io.packets_sent,
        "packets_recv": net_io.packets_recv
    }

async def get_system_temperature():
    try:
        temps = psutil.sensors_temperatures()
        if 'coretemp' in temps:
            return temps['coretemp'][0].current
        return None
    except Exception as e:
        logger.error(f"Error getting temperature: {e}")
        return None

async def get_system_stats():
    try:
        return {
            "cpu_usage": psutil.cpu_percent(),
            "memory_usage": psutil.virtual_memory().percent,
            "network_usage": await get_network_usage(),
            "disk_usage": psutil.disk_usage('/').percent,
            "temperature": await get_system_temperature(),
            "io_counters": psutil.disk_io_counters()._asdict()
        }
    except Exception as e:
        logger.error(f"Error getting system stats: {e}", exc_info=True)
        return {}

async def get_streams_info():
    try:
        # Replace with actual stream tracking logic
        return [{
            "id": f"stream_{i}",
            "title": f"Stream {i}",
            "quality": STREAM_QUALITY.collect()[0].samples[0].value,
            "duration": "00:45:30",
            "status": "Active"
        } for i in range(int(ACTIVE_STREAMS.collect()[0].samples[0].value))]
    except Exception as e:
        logger.error(f"Error getting streams info: {e}", exc_info=True)
        return []

@app.get("/")
async def dashboard(request: Request):
    try:
        system_stats = await get_system_stats()
        streams_info = await get_streams_info()
        return templates.TemplateResponse("index.html", {
            "request": request,
            "system_stats": system_stats,
            "streams_info": streams_info
        })
    except Exception as e:
        logger.error(f"Error rendering dashboard: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", {"request": request, "error": str(e)})

@app.websocket("/ws/metrics")
async def metrics_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            system_stats = await get_system_stats()
            streams_info = await get_streams_info()
            await websocket.send_json({
                "system_stats": system_stats,
                "streams_info": streams_info
            })
            await asyncio.sleep(5)  # Send updates every 5 seconds
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        websocket.close()

# Add cleanup on shutdown
@app.on_event("shutdown")
async def shutdown_event():
    await tautulli.close()

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
