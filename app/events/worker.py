"""Backward-compatible API for the split event processes.

Runtime entry points live in :mod:`app.events.publisher` and
:mod:`app.events.consumer`. Tests and older integrations can still import
``app.events.worker``; ``process`` forwards the patched SessionLocal to the
shared transaction module.
"""

from app.events import common as _common
from app.events.common import QueueSpec, add_event, dead_queues, queues, setup
from app.events.consumer import consumer
from app.events.publisher import publisher

SessionLocal = _common.SessionLocal


def process(name, data):
    _common.SessionLocal = SessionLocal
    return _common.process(name, data)


__all__ = [
    "QueueSpec",
    "SessionLocal",
    "add_event",
    "consumer",
    "dead_queues",
    "process",
    "publisher",
    "queues",
    "setup",
]
