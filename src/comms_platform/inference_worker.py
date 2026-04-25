import torch
from transformers import pipeline
import threading
import queue
from .utils.logger import get_logger

class InferenceWorker:
    def __init__(self, config, td_sender, thread_manager):
        self.config = config
        self.td_sender = td_sender
        self.thread_manager = thread_manager
        self.input_queue = queue.Queue()
        self.device = self._get_device()
        self.pipeline = self._load_pipeline()
        self.thread_manager.register("inference_worker", self.run)
        self.logger = get_logger("InferenceWorker")

    def _get_device(self):
        if torch.cuda.is_available() and self.config.DEVICE == "cuda":
            return "cuda"
        return "cpu"

    def _load_pipeline(self):
        pipe = pipeline(self.config.MODEL_NAME, device=0 if self.device == "cuda" else -1)
        # Warm-up
        with torch.inference_mode():
            pipe(["warmup"])
        return pipe

    def run(self, stop_event):
        while not stop_event.is_set():
            try:
                item = self.input_queue.get(timeout=0.1)
                result = self.pipeline(item)
                self.td_sender.enqueue("/td/feature", [result])
            except queue.Empty:
                continue
