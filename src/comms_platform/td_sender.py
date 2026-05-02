import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

from .utils.logger import get_logger


@dataclass
class SignalMessage:
    direction: str
    protocol: str
    address: str
    params: list[Any]
    source: str
    target: str
    timestamp: float = field(default_factory=time.time)


class TouchDesignerSender:
    """Signal gateway with OSC transport + generic stream publishing."""

    def __init__(self, config, thread_manager, event_bus=None):
        self.queue: queue.Queue[SignalMessage] = queue.Queue()
        self.osc_output_host = config.TD_HOST
        self.osc_output_port = config.TD_PORT
        self.osc_input_host = config.OSC_INPUT_HOST
        self.osc_input_port = config.OSC_INPUT_PORT
        self.client = SimpleUDPClient(self.osc_output_host, self.osc_output_port)
        self.lock = threading.Lock()
        self.thread_manager = thread_manager
        self.event_bus = event_bus
        self.logger = get_logger("TouchDesignerSender")
        self.thread_manager.register("signal_sender", self.run)
        self.thread_manager.register("signal_osc_receiver", self.listen_osc)

    def _publish(self, payload: SignalMessage):
        if self.event_bus is None:
            return
        self.event_bus.publish(
            {
                "timestamp": payload.timestamp,
                "direction": payload.direction,
                "protocol": payload.protocol,
                "address": payload.address,
                "params": payload.params,
                "source": payload.source,
                "target": payload.target,
            }
        )

    def send(self, address: str, params: Iterable[Any], source: str = "platform"):
        params_list = list(params)
        with self.lock:
            msg = OscMessageBuilder(address=address)
            for p in params_list:
                msg.add_arg(p)
            self.client.send(msg.build())
        self._publish(
            SignalMessage(
                direction="outbound",
                protocol="osc",
                address=address,
                params=params_list,
                source=source,
                target=f"{self.osc_output_host}:{self.osc_output_port}",
            )
        )

    def send_batch(self, messages: list[tuple[str, list[Any]]], source: str = "platform"):
        for address, params in messages:
            self.send(address, params, source=source)

    def run(self, stop_event):
        while not stop_event.is_set():
            try:
                item = self.queue.get(timeout=0.1)
                self.send(item.address, item.params, source=item.source)
            except queue.Empty:
                continue

    def enqueue(self, address: str, params: Iterable[Any], source: str = "platform"):
        self.queue.put(
            SignalMessage(
                direction="outbound",
                protocol="osc",
                address=address,
                params=list(params),
                source=source,
                target=f"{self.osc_output_host}:{self.osc_output_port}",
            )
        )

    def enqueue_batch(self, messages: list[tuple[str, list[Any]]], source: str = "platform"):
        for address, params in messages:
            self.enqueue(address, params, source=source)

    def publish_stream(
        self,
        address: str,
        params: Iterable[Any],
        source: str = "external-app",
        protocol: str = "stream",
        direction: str = "inbound",
        target: str = "platform",
    ):
        self._publish(
            SignalMessage(
                direction=direction,
                protocol=protocol,
                address=address,
                params=list(params),
                source=source,
                target=target,
            )
        )

    def listen_osc(self, stop_event):
        dispatcher = Dispatcher()

        def on_osc(address, *args):
            self._publish(
                SignalMessage(
                    direction="inbound",
                    protocol="osc",
                    address=address,
                    params=list(args),
                    source="touchdesigner-or-any-osc-client",
                    target="platform",
                )
            )

        dispatcher.set_default_handler(on_osc)
        server = ThreadingOSCUDPServer(
            (self.osc_input_host, self.osc_input_port), dispatcher
        )
        server.timeout = 0.2
        self.logger.info(
            "Listening for OSC input on %s:%s",
            self.osc_input_host,
            self.osc_input_port,
        )

        try:
            while not stop_event.is_set():
                server.handle_request()
        finally:
            server.server_close()
