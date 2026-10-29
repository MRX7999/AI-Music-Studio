"""Движки генерации: ACE-Step (локально), Suno через GPTunneL (облако), демо-синтезатор."""
from .acestep import AceStepGenerator
from .base import GeneratedTrack, GenerationCancelled, GenerationError, GenerationRequest, Generator
from .demo import DemoGenerator
from .gptunnel import GptunnelGenerator

ENGINES = {
    AceStepGenerator.id: AceStepGenerator,
    GptunnelGenerator.id: GptunnelGenerator,
    DemoGenerator.id: DemoGenerator,
}


def get_engine(engine_id: str, **kw) -> Generator:
    return ENGINES[engine_id](**kw)


__all__ = ["ENGINES", "get_engine", "GenerationRequest", "GeneratedTrack", "GenerationError",
           "GenerationCancelled", "Generator", "AceStepGenerator", "GptunnelGenerator", "DemoGenerator"]
