"""JARVIS: Specialist Worker Agent for Multi-Agent Architecture."""

__version__ = "0.1.0"

from jarvis.shared_bus import SharedBusProtocol
from jarvis.worker import JarvisWorker

__all__ = ["__version__", "SharedBusProtocol", "JarvisWorker"]
