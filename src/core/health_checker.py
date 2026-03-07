"""Health monitoring for all OMNIMIND services."""
import asyncio, logging, psutil
logger = logging.getLogger("omnimind.health")

class HealthChecker:
    def __init__(self, config: dict):
        self.interval = config.get("services", {}).get("health_monitor", {}).get("check_interval_seconds", 30)

    async def monitor_loop(self):
        while True:
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            if ram > 90:
                logger.warning(f"High RAM usage: {ram}%")
            if cpu > 95:
                logger.warning(f"High CPU usage: {cpu}%")
            await asyncio.sleep(self.interval)
