"""Detector plugins. Importing this package registers the built-in ones."""

from dqm_assistant.detectors.base import REGISTRY, Detector, NotJudged, build, register  # noqa: F401
from dqm_assistant.detectors import dqm_alarms, ks, remote, tranad, vision  # noqa: F401  (registration)
