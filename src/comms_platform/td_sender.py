import queue
from pythonosc.udp_client import SimpleUDPClient
from pythonosc.osc_bundle_builder import OscBundleBuilder
from pythonosc.osc_message_builder import OscMessageBuilder
import threading
from .utils.logger import get_logger

class TouchDesignerSender:
    def __init__(self, config, thread_manager, event_bus=None):
        self.queue = queue.Queue()
        self.client = SimpleUDPClient(config.TD_HOST, config.TD_PORT)
        self.lock = threading.Lock()
        self.thread_manager = thread_manager
        self.event_bus = event_bus
        self.thread_manager.register("td_sender", self.run)
        self.logger = get_logger("TouchDesignerSender")

    def send(self, address, params):
        with self.lock:
            msg = OscMessageBuilder(address=address)
            for p in params:
                msg.add_arg(p)
            self.client.send(msg.build())
        if self.event_bus is not None:
            self.event_bus.publish({"address": address, "params": params})

    def send_batch(self, messages):
        with self.lock:
            bundle = OscBundleBuilder(OscBundleBuilder.IMMEDIATELY)
            for address, params in messages:
                msg = OscMessageBuilder(address=address)
                for p in params:
                    msg.add_arg(p)
                bundle.add_content(msg.build())
            self.client.send(bundle.build())

    def run(self, stop_event):
        while not stop_event.is_set():
            try:
                item = self.queue.get(timeout=0.1)
                if isinstance(item, tuple) and len(item) == 2:
                    self.send(*item)
            except queue.Empty:
                continue

    def enqueue(self, address, params):
        self.queue.put((address, params))

    def enqueue_batch(self, messages):
        self.queue.put(messages)
