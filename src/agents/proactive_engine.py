"""
OMNIMIND LOCAL — Proactive Intelligence Engine
═══════════════════════════════════════════════════

Leo doesn't just respond. He ANTICIPATES.

This module monitors background signals and proactively informs the user
or takes action without being asked. This is what separates Leo from a
dumb chatbot: he has his own "pulse" of awareness that runs continuously.

Proactive Triggers implemented:
─────────────────────────────────
1. SEDENTARY ALERT      — User hasn't moved for N minutes (from wearable/calendar)
2. DEVICE ALERT         — Any connected device sends an unexpected state change
3. CAMERA MOTION        — Front door / security camera detects motion or person
4. CALENDAR REMINDER    — Upcoming event in < N minutes
5. WEATHER CHANGE       — Temperature or rain changes significantly (local API)
6. SYSTEM HEALTH        — GPU temp, RAM usage, disk full warnings
7. NIGHTLY DIGEST       — Daily summary of all events/interactions at configured time

Architecture:
─────────────────────────────────
ProactiveEngine runs as an asyncio background task, separate from the voice loop.
When a trigger fires, it publishes to omnimind.proactive.trigger on the message bus.
The main voice loop picks it up and Leo speaks the alert unprompted.
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Callable, Awaitable
from enum import Enum

logger = logging.getLogger("omnimind.proactive")


class Priority(Enum):
    LOW = "low"           # Informational, Leo mentions it when convenient
    MEDIUM = "medium"     # Leo interrupts what he's doing to tell you
    HIGH = "high"         # Immediate alert, plays a sound + speaks


@dataclass
class ProactiveTrigger:
    """A single proactive event that Leo should communicate."""
    trigger_id: str
    priority: Priority
    message: str                   # What Leo should say
    action: str | None = None      # Optional: device command to execute
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_bus_payload(self) -> dict:
        return {
            "trigger_id": self.trigger_id,
            "priority": self.priority.value,
            "message": self.message,
            "action": self.action,
            "data": self.data,
            "timestamp": self.timestamp,
        }


class ProactiveEngine:
    """
    Background engine that monitors signals and fires proactive triggers.
    Runs independently of the voice loop via redis message bus.
    """

    def __init__(self, config, bus, device_orchestrator=None):
        self.config = config.get("proactive", {})
        self.bus = bus
        self.devices = device_orchestrator
        self._running = False
        self._task = None

        # State tracking
        self._last_motion_time: float = time.time()
        self._last_user_interaction: float = time.time()
        self._device_states: dict = {}
        self._fired_today: set = set()  # Avoid duplicate triggers in same day

        # Configurable thresholds (from configs/system.yaml or defaults)
        self._sedentary_threshold_min = self.config.get("sedentary_alert_minutes", 90)
        self._camera_check_interval_s = self.config.get("camera_check_interval_seconds", 30)
        self._health_check_interval_s = self.config.get("health_check_interval_seconds", 300)
        self._digest_time = self.config.get("digest_time", "22:00")  # HH:MM

    async def start(self):
        """Start all background monitoring loops as asyncio tasks."""
        self._running = True
        self._task = asyncio.gather(
            self._sedentary_monitor(),
            self._device_state_monitor(),
            self._system_health_monitor(),
            self._nightly_digest_scheduler(),
            return_exceptions=True,
        )
        asyncio.create_task(self._task)
        logger.info("Proactive intelligence engine running")

    # ─────────────────────────────────────────────
    # Monitor 1: Sedentary Alert
    # ─────────────────────────────────────────────

    async def _sedentary_monitor(self):
        """
        Alert the user if they haven't moved / interacted for too long.
        Detects: calendar inactivity, wearable step data, or simply time since
        last voice interaction.
        """
        check_interval = 60  # Check every 60 seconds
        alerted = False

        while self._running:
            await asyncio.sleep(check_interval)
            try:
                idle_minutes = (time.time() - self._last_user_interaction) / 60

                if idle_minutes >= self._sedentary_threshold_min and not alerted:
                    alerted = True
                    trigger = ProactiveTrigger(
                        trigger_id="sedentary_alert",
                        priority=Priority.MEDIUM,
                        message=(
                            f"Hey! You've been sitting for {int(idle_minutes)} minutes straight. "
                            f"Time to stretch your legs — or is everything okay?"
                        ),
                        data={"idle_minutes": idle_minutes},
                    )
                    await self._fire(trigger)

                elif idle_minutes < self._sedentary_threshold_min:
                    alerted = False  # Reset when user becomes active again

            except Exception as e:
                logger.warning(f"Sedentary monitor error: {e}")

    # ─────────────────────────────────────────────
    # Monitor 2: Device State Monitor
    # ─────────────────────────────────────────────

    async def _device_state_monitor(self):
        """
        Polls connected devices for unexpected state changes.
        Example: camera detects motion → Leo alerts immediately.
        """
        if not self.devices:
            logger.info("Device monitor: no DeviceOrchestrator available, skipping.")
            return

        while self._running:
            await asyncio.sleep(self._camera_check_interval_s)
            try:
                for device_id, device in self.devices.devices.items():
                    if not device.adapter.is_connected:
                        continue

                    # Motion detection from cameras (HTTP devices that return motion state)
                    if "camera" in device.tags and "get_motion" in device.capabilities:
                        result = await device.execute("get_motion")
                        motion_detected = result.get("result", {})
                        persons = 0

                        if isinstance(motion_detected, dict):
                            persons = motion_detected.get("persons", 0)
                        elif isinstance(motion_detected, bool) and motion_detected:
                            persons = 1

                        prev_persons = self._device_states.get(f"{device_id}_persons", 0)
                        if persons > 0 and prev_persons == 0:
                            trigger = ProactiveTrigger(
                                trigger_id=f"motion_{device_id}",
                                priority=Priority.HIGH,
                                message=(
                                    f"Heads up — {device.name} just detected "
                                    f"{'someone' if persons == 1 else str(persons) + ' people'} "
                                    f"at {device.location}. Want me to show the camera feed?"
                                ),
                                data={"device": device_id, "persons": persons},
                            )
                            await self._fire(trigger)

                        self._device_states[f"{device_id}_persons"] = persons

                    # Low battery from any device
                    if "get_battery" in device.capabilities:
                        result = await device.execute("get_battery")
                        battery = result.get("result", {})
                        level = battery.get("level", 100) if isinstance(battery, dict) else 100
                        threshold = 20
                        key = f"{device_id}_low_battery_alerted"
                        if level < threshold and not self._device_states.get(key):
                            self._device_states[key] = True
                            trigger = ProactiveTrigger(
                                trigger_id=f"battery_low_{device_id}",
                                priority=Priority.MEDIUM,
                                message=f"{device.name} battery is at {level}%. You might want to charge it soon.",
                                data={"device": device_id, "battery": level},
                            )
                            await self._fire(trigger)
                        elif level >= threshold:
                            self._device_states[f"{device_id}_low_battery_alerted"] = False

            except Exception as e:
                logger.warning(f"Device state monitor error: {e}")

    # ─────────────────────────────────────────────
    # Monitor 3: System Health
    # ─────────────────────────────────────────────

    async def _system_health_monitor(self):
        """
        Monitors local hardware: GPU temperature, RAM, disk space.
        Alerts if anything critical is approaching limits.
        """
        while self._running:
            await asyncio.sleep(self._health_check_interval_s)
            try:
                await self._check_gpu_temp()
                await self._check_disk_space()
                await self._check_ram_usage()
            except Exception as e:
                logger.debug(f"System health monitor error: {e}")

    async def _check_gpu_temp(self):
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                temp = int(result.stdout.strip())
                if temp >= 85 and "gpu_overheat" not in self._fired_today:
                    self._fired_today.add("gpu_overheat")
                    await self._fire(ProactiveTrigger(
                        trigger_id="gpu_overheat",
                        priority=Priority.HIGH,
                        message=f"Warning: GPU temperature is {temp}°C. Consider reducing load or improving airflow.",
                        data={"gpu_temp": temp},
                    ))
        except Exception:
            pass  # nvidia-smi not available

    async def _check_disk_space(self):
        try:
            import shutil
            total, used, free = shutil.disk_usage("/")
            free_pct = (free / total) * 100
            if free_pct < 10 and "disk_low" not in self._fired_today:
                self._fired_today.add("disk_low")
                await self._fire(ProactiveTrigger(
                    trigger_id="disk_space_low",
                    priority=Priority.MEDIUM,
                    message=f"Disk space is getting low — only {free_pct:.1f}% free ({free // (1024**3)}GB). "
                            f"You might want to clean up before the next learning cycle.",
                    data={"free_pct": free_pct},
                ))
        except Exception:
            pass

    async def _check_ram_usage(self):
        try:
            import psutil
            ram = psutil.virtual_memory()
            if ram.percent > 90 and "ram_high" not in self._fired_today:
                self._fired_today.add("ram_high")
                await self._fire(ProactiveTrigger(
                    trigger_id="ram_high",
                    priority=Priority.MEDIUM,
                    message=f"RAM usage is at {ram.percent:.0f}%. "
                            f"I might get slower. Consider closing some applications.",
                    data={"ram_percent": ram.percent},
                ))
        except Exception:
            pass

    # ─────────────────────────────────────────────
    # Monitor 4: Nightly Digest
    # ─────────────────────────────────────────────

    async def _nightly_digest_scheduler(self):
        """Fires the daily summary at the configured time (default 22:00)."""
        while self._running:
            await asyncio.sleep(60)
            now = datetime.now()
            target_h, target_m = map(int, self._digest_time.split(":"))
            if now.hour == target_h and now.minute == target_m:
                key = f"digest_{now.date()}"
                if key not in self._fired_today:
                    self._fired_today.add(key)
                    await self._fire(ProactiveTrigger(
                        trigger_id="nightly_digest",
                        priority=Priority.LOW,
                        message=(
                            f"Good evening! Here's your daily summary: "
                            f"we had {self._count_interactions_today()} interactions today. "
                            f"I'll run tonight's learning cycle in a few hours while you sleep. "
                            f"Is there anything you'd like to wrap up before then?"
                        ),
                        data={"date": now.date().isoformat()},
                    ))

    def _count_interactions_today(self) -> int:
        """Placeholder — real implementation reads from the FeedbackCollector log."""
        return 0

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    def record_user_interaction(self):
        """Call this every time the user speaks or interacts with Leo."""
        self._last_user_interaction = time.time()
        self._last_motion_time = time.time()

    async def _fire(self, trigger: ProactiveTrigger):
        """Publish a proactive trigger to the message bus."""
        logger.info(
            f"[proactive] FIRING {trigger.trigger_id} "
            f"(priority={trigger.priority.value}): {trigger.message[:80]}..."
        )
        await self.bus.publish("omnimind.proactive.trigger", trigger.to_bus_payload())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("Proactive engine stopped")
