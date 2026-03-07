"""Redis Streams message bus for inter-module communication."""
import asyncio
import json
import logging
import redis.asyncio as redis

logger = logging.getLogger("omnimind.bus")

class MessageBus:
    def __init__(self, config: dict):
        self.config = config.get("message_bus", {})
        self.redis_config = config.get("services", {}).get("redis", {})
        self.client = None

    async def connect(self):
        host = self.redis_config.get("host", "127.0.0.1")
        port = self.redis_config.get("port", 6379)
        self.client = redis.Redis(host=host, port=port, decode_responses=True)
        await self.client.ping()
        logger.info(f"Connected to Redis at {host}:{port}")

    async def publish(self, channel: str, data: dict):
        await self.client.xadd(channel, {"data": json.dumps(data)}, maxlen=10000)

    async def subscribe(self, channel: str, callback, group: str = "omnimind"):
        try:
            await self.client.xgroup_create(channel, group, id="0", mkstream=True)
        except redis.ResponseError:
            pass
        while True:
            msgs = await self.client.xreadgroup(group, "worker", {channel: ">"}, count=1, block=1000)
            for stream, entries in msgs:
                for msg_id, fields in entries:
                    data = json.loads(fields.get("data", "{}"))
                    await callback(data)
                    await self.client.xack(channel, group, msg_id)

    async def disconnect(self):
        if self.client:
            await self.client.close()
