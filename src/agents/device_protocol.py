"""
OMNIMIND LOCAL — Universal Device Protocol (UDP)
═══════════════════════════════════════════════════

The abstraction layer that lets Leo control ANY device.

Instead of writing a custom agent for every device, we define a universal
protocol. Any device — drone, car, robot, camera, watch, thermostat,
3D printer, EV charger, satellite dish — registers itself with:

  1. Identity: what it is
  2. Capabilities: what it can do (as callable tools)
  3. State: what it currently knows about itself
  4. Protocol: how to talk to it (serial, MQTT, HTTP, BLE, UDP, WebSocket, TCP...)

Leo doesn't need to know HOW a device works internally.
He only needs to know WHAT it can do and call those capabilities.

Architecture:
┌─────────────────────────────────────────────────────┐
│                   LEO (LLM)                          │
│         "Turn on the living room light"              │
│         "Fly the drone to the backyard"              │
│         "What does the car dashboard say?"           │
└──────────────────────┬──────────────────────────────┘
                       │ function call
                       ▼
┌─────────────────────────────────────────────────────┐
│              DEVICE ORCHESTRATOR                     │
│   Routes commands to registered devices by           │
│   matching capability names to device registry       │
└──────────────────────┬──────────────────────────────┘
                       │
        ┌──────────────┼──────────────────┐
        ▼              ▼                  ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│   ADAPTER    │ │   ADAPTER    │ │   ADAPTER    │
│   Serial     │ │   MQTT       │ │   HTTP/REST  │
│   (Arduino)  │ │ (Home Asst)  │ │  (API)       │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       ▼                ▼                ▼
  [Servo arm]     [Smart bulb]     [Drone SDK]
  [Relay]         [Thermostat]     [Car API]
  [Pan-tilt]      [Lock]           [Camera]
"""

import asyncio
import logging
import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from pathlib import Path

logger = logging.getLogger("omnimind.devices")


# ─────────────────────────────────────
# Device Capability Definition
# ─────────────────────────────────────

class DeviceCapability:
    """A single thing a device can do, exposed as an LLM tool."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict = None,
        requires_confirmation: bool = False,
        category: str = "action",  # action | query | stream
    ):
        self.name = name
        self.description = description
        self.parameters = parameters or {"type": "object", "properties": {}, "required": []}
        self.requires_confirmation = requires_confirmation
        self.category = category

    def to_tool_schema(self, device_id: str) -> dict:
        """Convert to LLM function calling schema."""
        return {
            "type": "function",
            "function": {
                "name": f"{device_id}__{self.name}",
                "description": f"[{device_id}] {self.description}",
                "parameters": self.parameters,
            }
        }


# ─────────────────────────────────────
# Communication Adapters
# ─────────────────────────────────────

class CommunicationAdapter(ABC):
    """Base class for all communication protocols."""

    @abstractmethod
    async def connect(self, config: dict) -> bool:
        pass

    @abstractmethod
    async def send(self, command: str, params: dict = None) -> Any:
        pass

    @abstractmethod
    async def receive(self) -> Any:
        pass

    @abstractmethod
    async def disconnect(self):
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        pass


class SerialAdapter(CommunicationAdapter):
    """Serial/USB communication (Arduino, ESP32, robotic arms, etc.)."""

    def __init__(self):
        self._conn = None
        self._connected = False

    async def connect(self, config: dict) -> bool:
        try:
            import serial
            self._conn = serial.Serial(
                port=config.get("port", "/dev/ttyUSB0"),
                baudrate=config.get("baud", 9600),
                timeout=config.get("timeout", 2),
            )
            await asyncio.sleep(2)  # Wait for device reset
            self._connected = True
            return True
        except Exception as e:
            logger.error(f"Serial connect failed: {e}")
            return False

    async def send(self, command: str, params: dict = None) -> Any:
        if not self._conn:
            return {"error": "Not connected"}
        try:
            msg = command
            if params:
                msg += " " + " ".join(str(v) for v in params.values())
            self._conn.write(f"{msg}\n".encode())
            await asyncio.sleep(0.1)
            if self._conn.in_waiting:
                return self._conn.readline().decode().strip()
            return "OK"
        except Exception as e:
            return {"error": str(e)}

    async def receive(self) -> Any:
        if self._conn and self._conn.in_waiting:
            return self._conn.readline().decode().strip()
        return None

    async def disconnect(self):
        if self._conn:
            self._conn.close()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected


class MQTTAdapter(CommunicationAdapter):
    """MQTT communication (Home Assistant, IoT devices, smart home)."""

    def __init__(self):
        self._client = None
        self._connected = False
        self._messages = asyncio.Queue()

    async def connect(self, config: dict) -> bool:
        try:
            import paho.mqtt.client as mqtt
            self._client = mqtt.Client()
            if config.get("username"):
                self._client.username_pw_set(config["username"], config.get("password", ""))
            self._client.on_message = lambda c, u, m: self._messages.put_nowait(m.payload.decode())
            self._client.connect(config.get("host", "127.0.0.1"), config.get("port", 1883))
            self._client.loop_start()
            self._connected = True
            return True
        except Exception as e:
            logger.error(f"MQTT connect failed: {e}")
            return False

    async def send(self, command: str, params: dict = None) -> Any:
        if not self._client:
            return {"error": "Not connected"}
        topic = params.get("topic", command) if params else command
        payload = params.get("payload", "") if params else ""
        self._client.publish(topic, json.dumps(payload) if isinstance(payload, dict) else str(payload))
        return "OK"

    async def receive(self) -> Any:
        try:
            return self._messages.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def disconnect(self):
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected


class HTTPAdapter(CommunicationAdapter):
    """HTTP/REST API communication (cloud-free APIs, local services, SDKs)."""

    def __init__(self):
        self._base_url = ""
        self._headers = {}
        self._client = None
        self._connected = False

    async def connect(self, config: dict) -> bool:
        try:
            import httpx
            self._base_url = config.get("base_url", "http://127.0.0.1")
            self._headers = config.get("headers", {})
            self._client = httpx.AsyncClient(timeout=config.get("timeout", 10))
            # Test connection
            r = await self._client.get(f"{self._base_url}/{config.get('health_endpoint', 'health')}")
            self._connected = r.status_code < 500
            return self._connected
        except Exception as e:
            logger.error(f"HTTP connect failed: {e}")
            return False

    async def send(self, command: str, params: dict = None) -> Any:
        if not self._client:
            return {"error": "Not connected"}
        method = (params or {}).pop("_method", "POST")
        url = f"{self._base_url}/{command}"
        try:
            if method == "GET":
                r = await self._client.get(url, params=params)
            else:
                r = await self._client.post(url, json=params)
            return r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
        except Exception as e:
            return {"error": str(e)}

    async def receive(self) -> Any:
        return None

    async def disconnect(self):
        if self._client:
            await self._client.aclose()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected


class UDPAdapter(CommunicationAdapter):
    """UDP communication (drones like Tello, custom protocols)."""

    def __init__(self):
        self._socket = None
        self._address = None
        self._connected = False

    async def connect(self, config: dict) -> bool:
        try:
            import socket
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.bind(("", config.get("local_port", 8889)))
            self._socket.settimeout(config.get("timeout", 10))
            self._address = (config.get("host", "192.168.10.1"), config.get("port", 8889))
            # Send init command if specified
            init_cmd = config.get("init_command", "command")
            if init_cmd:
                self._socket.sendto(init_cmd.encode(), self._address)
                response = self._socket.recv(1024).decode()
                self._connected = response.lower() in ("ok", "true", "connected")
            else:
                self._connected = True
            return self._connected
        except Exception as e:
            logger.error(f"UDP connect failed: {e}")
            return False

    async def send(self, command: str, params: dict = None) -> Any:
        if not self._socket:
            return {"error": "Not connected"}
        try:
            msg = command
            if params:
                msg += " " + " ".join(str(v) for v in params.values())
            self._socket.sendto(msg.encode(), self._address)
            response = self._socket.recv(1024).decode()
            return response
        except Exception as e:
            return {"error": str(e)}

    async def receive(self) -> Any:
        try:
            return self._socket.recv(1024).decode()
        except:
            return None

    async def disconnect(self):
        if self._socket:
            self._socket.close()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected


class BLEAdapter(CommunicationAdapter):
    """Bluetooth Low Energy (wearables, sensors, OBD-II adapters)."""

    def __init__(self):
        self._client = None
        self._connected = False

    async def connect(self, config: dict) -> bool:
        try:
            from bleak import BleakClient
            address = config.get("mac_address")
            self._client = BleakClient(address)
            await self._client.connect()
            self._connected = self._client.is_connected
            return self._connected
        except Exception as e:
            logger.error(f"BLE connect failed: {e}")
            return False

    async def send(self, command: str, params: dict = None) -> Any:
        if not self._client:
            return {"error": "Not connected"}
        char_uuid = (params or {}).get("characteristic", command)
        data = (params or {}).get("data", b"")
        if isinstance(data, str):
            data = data.encode()
        await self._client.write_gatt_char(char_uuid, data)
        return "OK"

    async def receive(self) -> Any:
        return None

    async def disconnect(self):
        if self._client:
            await self._client.disconnect()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected


class WebSocketAdapter(CommunicationAdapter):
    """WebSocket communication (real-time APIs, custom services)."""

    def __init__(self):
        self._ws = None
        self._connected = False

    async def connect(self, config: dict) -> bool:
        try:
            import websockets
            self._ws = await websockets.connect(config.get("url", "ws://127.0.0.1:8080"))
            self._connected = True
            return True
        except Exception as e:
            logger.error(f"WebSocket connect failed: {e}")
            return False

    async def send(self, command: str, params: dict = None) -> Any:
        if not self._ws:
            return {"error": "Not connected"}
        payload = json.dumps({"command": command, "params": params or {}})
        await self._ws.send(payload)
        response = await self._ws.recv()
        try:
            return json.loads(response)
        except:
            return response

    async def receive(self) -> Any:
        if self._ws:
            return await self._ws.recv()
        return None

    async def disconnect(self):
        if self._ws:
            await self._ws.close()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected


class TunnelAdapter(CommunicationAdapter):
    """
    VPN/Tunnel adapter for long-range device control.
    Wraps any other adapter over a WireGuard/Tailscale/ZeroTier VPN.
    The device can be anywhere in the world with a cellular connection.
    
    How it works:
    1. Remote device runs WireGuard client + a local service
    2. VPN assigns it a fixed IP (e.g. 10.0.0.50)
    3. Leo talks to it via HTTP/WebSocket on the VPN IP
    4. All traffic is encrypted end-to-end through the tunnel
    
    This adapter is a wrapper — it creates an inner adapter (http, websocket, etc.)
    and routes it through the VPN IP.
    """

    def __init__(self):
        self._inner_adapter = None
        self._connected = False

    async def connect(self, config: dict) -> bool:
        # The VPN must already be running (WireGuard/Tailscale)
        # We just use the VPN IP as if it were a local device
        inner_protocol = config.get("inner_protocol", "http")
        vpn_ip = config.get("vpn_ip")  # e.g. "10.0.0.50"
        
        if not vpn_ip:
            logger.error("Tunnel adapter requires 'vpn_ip' in config")
            return False

        # Create inner adapter with VPN-routed config
        inner_class = ADAPTERS.get(inner_protocol)
        if not inner_class:
            logger.error(f"Unknown inner protocol: {inner_protocol}")
            return False
        
        self._inner_adapter = inner_class()
        
        # Rewrite connection config to use VPN IP
        inner_config = dict(config.get("inner_connection", {}))
        inner_config.setdefault("host", vpn_ip)
        inner_config.setdefault("base_url", f"http://{vpn_ip}:{config.get('port', 8080)}")
        inner_config.setdefault("url", f"ws://{vpn_ip}:{config.get('port', 8080)}")
        
        self._connected = await self._inner_adapter.connect(inner_config)
        if self._connected:
            logger.info(f"Tunnel connected to {vpn_ip} via {inner_protocol}")
        return self._connected

    async def send(self, command: str, params: dict = None) -> Any:
        if self._inner_adapter:
            return await self._inner_adapter.send(command, params)
        return {"error": "Tunnel not connected"}

    async def receive(self) -> Any:
        if self._inner_adapter:
            return await self._inner_adapter.receive()
        return None

    async def disconnect(self):
        if self._inner_adapter:
            await self._inner_adapter.disconnect()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected


# Adapter registry
ADAPTERS = {
    "serial": SerialAdapter,
    "mqtt": MQTTAdapter,
    "http": HTTPAdapter,
    "udp": UDPAdapter,
    "ble": BLEAdapter,
    "websocket": WebSocketAdapter,
    "tunnel": TunnelAdapter,
}


# ─────────────────────────────────────
# Universal Device
# ─────────────────────────────────────

class UniversalDevice:
    """
    A single connected device with its adapter and capabilities.
    This is what gets registered in the DeviceOrchestrator.
    """

    def __init__(self, device_id: str, config: dict):
        self.id = device_id
        self.config = config
        self.name = config.get("name", device_id)
        self.type = config.get("type", "unknown")
        self.description = config.get("description", "")
        self.location = config.get("location", "")
        self.tags = config.get("tags", [])
        self.state = {}
        self.last_seen = None

        # Create adapter
        protocol = config.get("protocol", "http")
        adapter_class = ADAPTERS.get(protocol)
        if not adapter_class:
            raise ValueError(f"Unknown protocol: {protocol}. Available: {list(ADAPTERS.keys())}")
        self.adapter = adapter_class()

        # Load capabilities
        self.capabilities = {}
        for cap_config in config.get("capabilities", []):
            cap = DeviceCapability(
                name=cap_config["name"],
                description=cap_config.get("description", ""),
                parameters=cap_config.get("parameters"),
                requires_confirmation=cap_config.get("requires_confirmation", False),
                category=cap_config.get("category", "action"),
            )
            self.capabilities[cap.name] = cap

    async def connect(self) -> bool:
        result = await self.adapter.connect(self.config.get("connection", {}))
        if result:
            self.last_seen = datetime.now()
        return result

    async def execute(self, capability_name: str, params: dict = None) -> dict:
        cap = self.capabilities.get(capability_name)
        if not cap:
            return {"error": f"Device '{self.id}' has no capability '{capability_name}'"}
        if not self.adapter.is_connected:
            return {"error": f"Device '{self.id}' is not connected"}

        # Map capability to adapter command
        command_map = self.config.get("command_map", {})
        command = command_map.get(capability_name, capability_name)

        self.last_seen = datetime.now()
        result = await self.adapter.send(command, params)

        # Update device state if the capability returns state info
        if isinstance(result, dict) and "state" in result:
            self.state.update(result["state"])

        return {"device": self.id, "capability": capability_name, "result": result}

    def get_tools(self) -> list:
        """Get all capabilities as LLM tool schemas."""
        return [cap.to_tool_schema(self.id) for cap in self.capabilities.values()]

    def get_status(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "location": self.location,
            "connected": self.adapter.is_connected,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "state": self.state,
            "capabilities": list(self.capabilities.keys()),
        }

    async def disconnect(self):
        await self.adapter.disconnect()


# ─────────────────────────────────────
# Device Orchestrator
# ─────────────────────────────────────

class DeviceOrchestrator:
    """
    Central registry for all connected devices.
    Routes Leo's commands to the right device and capability.
    Discovers devices, manages connections, aggregates tools for the LLM.
    """

    def __init__(self, config: dict, bus):
        self.config = config
        self.bus = bus
        self.devices: dict[str, UniversalDevice] = {}
        self.event_log = []

    async def start(self):
        # Load devices from config
        devices_config = self.config.get("devices", {}).get("registered", [])
        for dev_config in devices_config:
            device_id = dev_config.get("id")
            if not device_id:
                continue
            try:
                device = UniversalDevice(device_id, dev_config)
                self.devices[device_id] = device
                logger.info(f"  Device registered: {device_id} ({device.type})")

                # Auto-connect if configured
                if dev_config.get("auto_connect", False):
                    connected = await device.connect()
                    if connected:
                        logger.info(f"    ✓ Connected")
                    else:
                        logger.warning(f"    ✗ Connection failed")

            except Exception as e:
                logger.error(f"  Failed to register device {device_id}: {e}")

        logger.info(f"Device orchestrator ready ({len(self.devices)} devices)")

    async def execute(self, tool_call: str, params: dict = None) -> dict:
        """
        Execute a tool call from Leo.
        Tool names are formatted as: {device_id}__{capability_name}
        """
        if "__" not in tool_call:
            return {"error": f"Invalid tool format: {tool_call}. Expected: device_id__capability"}

        device_id, capability = tool_call.split("__", 1)

        # Special meta-commands
        if device_id == "devices":
            return await self._meta_command(capability, params)

        device = self.devices.get(device_id)
        if not device:
            return {"error": f"Device '{device_id}' not found. Available: {list(self.devices.keys())}"}

        result = await device.execute(capability, params)

        # Log event
        self.event_log.append({
            "timestamp": datetime.now().isoformat(),
            "device": device_id,
            "capability": capability,
            "params": params,
            "result": result,
        })

        # Publish to bus for other modules
        await self.bus.publish("omnimind.agent.response", {
            "source": "device_orchestrator",
            "device": device_id,
            "capability": capability,
            "result": result,
        })

        return result

    async def _meta_command(self, command: str, params: dict) -> dict:
        """Meta-commands for device management."""
        if command == "list":
            return {
                "devices": [d.get_status() for d in self.devices.values()]
            }
        elif command == "connect":
            device_id = (params or {}).get("device_id")
            device = self.devices.get(device_id)
            if not device:
                return {"error": f"Device '{device_id}' not found"}
            success = await device.connect()
            return {"device": device_id, "connected": success}
        elif command == "disconnect":
            device_id = (params or {}).get("device_id")
            device = self.devices.get(device_id)
            if device:
                await device.disconnect()
            return {"device": device_id, "disconnected": True}
        elif command == "status":
            device_id = (params or {}).get("device_id")
            device = self.devices.get(device_id)
            if device:
                return device.get_status()
            return {"error": f"Device '{device_id}' not found"}
        return {"error": f"Unknown meta-command: {command}"}

    def get_all_tools(self) -> list:
        """
        Get ALL tools from ALL connected devices.
        These are injected into the LLM's tool list so Leo can call any device.
        """
        tools = []
        # Meta tools (device management)
        tools.append({
            "type": "function",
            "function": {
                "name": "devices__list",
                "description": "List all registered devices and their status (connected, capabilities, location).",
                "parameters": {"type": "object", "properties": {}, "required": []},
            }
        })
        tools.append({
            "type": "function",
            "function": {
                "name": "devices__connect",
                "description": "Connect to a specific device.",
                "parameters": {
                    "type": "object",
                    "properties": {"device_id": {"type": "string"}},
                    "required": ["device_id"],
                }
            }
        })
        # Device-specific tools
        for device in self.devices.values():
            if device.adapter.is_connected:
                tools.extend(device.get_tools())
        return tools

    async def stop(self):
        for device in self.devices.values():
            try:
                await device.disconnect()
            except:
                pass
