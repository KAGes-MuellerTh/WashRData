"""Home Assistant independent cycle detection and program recognition."""

from .detector import CycleDetector
from .learning import LearnedStats
from .matching import MatchResult, ProgramMatcher
from .model import (
    ACTIVE_STATES,
    AUTO_LABEL_CONFIDENCE,
    PRESETS,
    SHOW_CONFIDENCE,
    CycleRecord,
    DetectorConfig,
    DeviceType,
    Event,
    EventKind,
    LabelSource,
    State,
)
from .tracker import CURRENT, LAST, Accuracy, ProgramAccuracy, Tracker

__all__ = [
    "ACTIVE_STATES",
    "AUTO_LABEL_CONFIDENCE",
    "CURRENT",
    "LAST",
    "PRESETS",
    "SHOW_CONFIDENCE",
    "Accuracy",
    "CycleDetector",
    "CycleRecord",
    "DetectorConfig",
    "DeviceType",
    "Event",
    "EventKind",
    "LabelSource",
    "LearnedStats",
    "MatchResult",
    "ProgramAccuracy",
    "ProgramMatcher",
    "State",
    "Tracker",
]
