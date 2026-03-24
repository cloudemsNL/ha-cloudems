# CloudEMS AI module — v1.0.0
# Provider pattern: OnnxProvider (default) + extensible for Ollama/OpenAI/AdaptiveHome
from .provider import AIProvider, AIModelContract, PredictionResult
from .onnx_provider import OnnxProvider
from .registry import AIRegistry

__all__ = ["AIProvider", "AIModelContract", "PredictionResult", "OnnxProvider", "AIRegistry"]
