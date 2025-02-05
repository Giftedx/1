import logging
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from src.metrics import ACTIVE_STREAMS, STREAM_QUALITY
from src.core.metrics_manager import MetricsManager

logger = logging.getLogger(__name__)
app = FastAPI()
templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")
metrics_manager = MetricsManager()

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
            stats = await metrics_manager.get_real_time_stats()
            await websocket.send_json(stats)
            await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await websocket.close()

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, ssl_context='adhoc')
