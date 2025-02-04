import aiohttp
import asyncio
import logging
from typing import TypedDict, Dict, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, RetryError
from prometheus_client import Counter, Histogram

from src.metrics import ACTIVE_STREAMS
from src.utils.config import Config
from src.core.exceptions import AlertSendException

logger = logging.getLogger(__name__)

# Add metrics
alert_send_duration = Histogram('alert_send_duration_seconds', 'Time spent sending alerts')
alert_failures = Counter('alert_send_failures_total', 'Number of failed alert attempts')

class AlertConfig(TypedDict):
    alert_url: str
    auth_token: str
    environment: str

class AlertService:
    def __init__(self, config: AlertConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
        self._retries = 0
        self._max_retries = 3

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self.config['auth_token']}"} )
        return self._session

    @retry(stop=stop_after_attempt(3), 
           wait=wait_exponential(multiplier=1, min=4, max=10),
           retry_error_callback=lambda retry_state: alert_failures.inc())
    async def send_alert(self, message: str, severity: str = "warning") -> None:
        async with alert_send_duration.time():
            session = await self._get_session()
            payload = {
                "message": message,
                "severity": severity,
                "environment": self.config["environment"]
            }
            
            async with session.post(self.config["alert_url"], json=payload) as response:
                if response.status not in (200, 201):
                    raise AlertSendException(
                        f"Failed to send alert: {response.status}",
                        self.config["alert_url"]
                    )

    async def cleanup(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

async def check_active_streams(alert_service: AlertService) -> None:
    config = Config()
    while True:
        try:
            active_count = ACTIVE_STREAMS.get_current_value()
            if active_count > config.MAX_CONCURRENT_STREAMS:
                await alert_service.send_alert(
                    f"High number of active streams: {active_count}/{config.MAX_CONCURRENT_STREAMS}"
                )
        except Exception as e:
            logger.error(f"Stream monitoring error: {e}", exc_info=True)
        await asyncio.sleep(60)

async def monitor_services(alert_service: AlertService):
    await asyncio.gather(
        check_active_streams(alert_service),
        # Add other monitoring tasks here
    )