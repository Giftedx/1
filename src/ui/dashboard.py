import logging
import psutil
import asyncio
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from src.metrics import ACTIVE_STREAMS, STREAM_QUALITY
from src.core.metrics_manager import MetricsManager
from src.core.tautulli_client import TautulliClient
import os

logger = logging.getLogger(__name__)
app = FastAPI()
templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")
metrics_manager = MetricsManager()

# Initialize Tautulli client
tautulli = TautulliClient(
    base_url=os.getenv('TAUTULLI_URL', 'http://localhost:8181'),
    api_key=os.getenv('TAUTULLI_API_KEY')
)

async def get_system_stats():
    return {
        "cpu_usage": psutil.cpu_percent(),
        "memory_usage": psutil.virtual_memory().percent,
        "network_usage": await get_network_usage(),
        "disk_usage": psutil.disk_usage('/').percent,
        "temperature": await get_system_temperature(),
        "io_counters": psutil.disk_io_counters()._asdict()
    }

async def get_streams_info():
    # Mock data - replace with actual stream tracking
    return [{
        "id": f"stream_{i}",
        "title": f"Stream {i}",
        "quality": STREAM_QUALITY.collect()[0].samples[0].value,
        "duration": "00:45:30",
        "status": "Active"
    } for i in range(int(ACTIVE_STREAMS.collect()[0].samples[0].value))]

@app.get("/")
async def dashboard(request):
    stats = {
        "active_streams": ACTIVE_STREAMS.collect()[0].samples[0].value,
        "stream_quality": STREAM_QUALITY.collect()[0].samples[0].value,
        "system_stats": await metrics_manager.get_system_stats()
    }
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "stats": stats}
    )

@app.websocket("/ws/metrics")
async def metrics_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Get Tautulli stream data
            plex_data = await tautulli.get_stream_data()
            
            stats = {
                "active_streams": ACTIVE_STREAMS.collect()[0].samples[0].value,
                "stream_quality": STREAM_QUALITY.collect()[0].samples[0].value,
                "system_stats": await get_system_stats(),
                "streams": await get_streams_info(),
                "plex_streams": plex_data['current_streams'],
                "bandwidth_history": plex_data['bandwidth_history'],
                "platform_stats": plex_data['platform_breakdown'],
                "quality_stats": plex_data['quality_breakdown'],
                "total_bandwidth": plex_data['total_bandwidth']
            }
            await websocket.send_json(stats)
            await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await websocket.close()

# Add cleanup on shutdown
@app.on_event("shutdown")
async def shutdown_event():
    await tautulli.close()

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, ssl_context='adhoc')
