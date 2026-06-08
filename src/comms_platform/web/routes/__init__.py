from .agent import register_agent_routes
from .core import register_core_routes
from .inference import register_inference_routes
from .media import register_media_routes
from .signals import register_signal_routes
from .third_party import register_third_party_routes


def register_routes(app, ctx, unreal_orchestrator) -> None:
    register_core_routes(app, ctx)
    register_agent_routes(app, ctx)
    register_inference_routes(app, ctx)
    register_media_routes(app)
    register_third_party_routes(app, ctx, unreal_orchestrator)
    register_signal_routes(app, ctx)
