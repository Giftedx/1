from typing import Dict, Optional
from prometheus_client import Counter, Gauge, Histogram
import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

ALERT_COUNTER = Counter('alert_total', 'Total number of alerts sent', ['type', 'severity'])
ALERT_FAILURES = Counter('alert_failures_total', 'Number of failed alert attempts')

class PrometheusAlerts:
    def __init__(self, alert_config: Dict[str, str]):
        """
        Initialize PrometheusAlerts with the given alert configuration.

        :param alert_config: A dictionary containing alert configuration parameters.
        """
        self.alert_config = alert_config
        self._session: Optional[aiohttp.ClientSession] = None
        self._metrics = {
            'alert_latency': Histogram('alert_send_latency_seconds', 
                                     'Alert sending latency'),
            'alert_failures': Counter('alert_failures_total', 
                                    'Number of failed alerts', 
                                    ['type'])
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def send_alert(self, message: str, alert_type: str = "general", severity: str = "warning") -> None:
        try:
            session = self._session or await self._get_session()
            async with session.post(
                self.alert_config.get("alert_url", ""),
                json={
                    "message": message,
                    "alert_type": alert_type,
                    "severity": severity
                }
            ) as response:
                if response.status not in (200, 201):
                    ALERT_FAILURES.labels(type=alert_type).inc()
                    raise Exception(f"Alert sending failed with status {response.status}")
                # Optionally, record latency if available.
                self._metrics['alert_latency'].observe(0)  # Replace 0 with measured latency if needed.
                ALERT_COUNTER.labels(type=alert_type, severity=severity).inc()
        except Exception as e:
            ALERT_FAILURES.labels(type=alert_type).inc()
            raise e

    async def cleanup(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

# ...existing code...