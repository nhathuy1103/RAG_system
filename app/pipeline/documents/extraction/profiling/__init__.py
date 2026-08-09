"""Page profiling and adaptive extraction routing."""

from app.pipeline.documents.extraction.profiling.config import (
    DEFAULT_PHASE2_CONFIG,
    PerformanceConfig,
    Phase2Config,
    ProfilingConfig,
    RoutingConfig,
    RoutingMode,
)
from app.pipeline.documents.extraction.profiling.models import (
    DownstreamCapabilityHints,
    ExtractionRoute,
    PageClass,
    PageClassification,
    PageProfile,
    ProfileStatus,
    RouteSource,
    RoutingDecision,
    SignalFailure,
)
from app.pipeline.documents.extraction.profiling.profiler import PageProfiler
from app.pipeline.documents.extraction.profiling.router import AdaptiveRouter

__all__ = [
    "DEFAULT_PHASE2_CONFIG",
    "AdaptiveRouter",
    "DownstreamCapabilityHints",
    "ExtractionRoute",
    "PageClassification",
    "PageClass",
    "PageProfile",
    "PageProfiler",
    "PerformanceConfig",
    "Phase2Config",
    "ProfileStatus",
    "ProfilingConfig",
    "RouteSource",
    "RoutingConfig",
    "RoutingDecision",
    "RoutingMode",
    "SignalFailure",
]
