from .core import register_core_routes
from .inference import register_inference_routes
from .media import register_media_routes


def register_routes(app, ctx) -> None:
    register_core_routes(app, ctx)
    register_inference_routes(app, ctx)
    register_media_routes(app)
