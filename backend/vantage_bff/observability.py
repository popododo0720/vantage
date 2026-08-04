from __future__ import annotations

import json
import logging
import math
import threading
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from time import monotonic

_BUCKETS = (0.05, 0.1, 0.25, 0.3, 0.6, 0.8, 1.5, 3.0, 4.0, 10.0)
_SECRET_FIELDS = {"password", "token", "authorization", "cookie", "csrf", "private_key"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, "fields", {})
        if isinstance(fields, Mapping):
            for key, value in fields.items():
                if key.casefold() not in _SECRET_FIELDS:
                    payload[str(key)] = value
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=True, default=str)


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("vantage")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


class Metrics:
    """Small dependency-free Prometheus exporter with OpenTelemetry-friendly names."""

    def __init__(self) -> None:
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = defaultdict(
            lambda: [0.0] * (len(_BUCKETS) + 2)
        )
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._lock = threading.Lock()

    def increment(self, name: str, labels: Mapping[str, str], amount: float = 1.0) -> None:
        with self._lock:
            self._counters[(name, _labels(labels))] += amount

    def gauge_add(self, name: str, labels: Mapping[str, str], amount: float) -> None:
        with self._lock:
            self._gauges[(name, _labels(labels))] += amount

    def observe(self, name: str, labels: Mapping[str, str], value: float) -> None:
        with self._lock:
            values = self._histograms[(name, _labels(labels))]
            for index, bucket in enumerate(_BUCKETS):
                if value <= bucket:
                    values[index] += 1
            values[len(_BUCKETS)] += 1
            values[len(_BUCKETS) + 1] += value

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for (name, labels), value in sorted(self._counters.items()):
                lines.append(f"{name}_total{_render_labels(labels)} {value:g}")
            for (name, labels), value in sorted(self._gauges.items()):
                lines.append(f"{name}{_render_labels(labels)} {value:g}")
            for (name, labels), values in sorted(self._histograms.items()):
                for index, bucket in enumerate(_BUCKETS):
                    bucket_labels = (*labels, ("le", f"{bucket:g}"))
                    lines.append(f"{name}_bucket{_render_labels(bucket_labels)} {values[index]:g}")
                inf_labels = (*labels, ("le", "+Inf"))
                lines.append(f"{name}_bucket{_render_labels(inf_labels)} {values[len(_BUCKETS)]:g}")
                lines.append(f"{name}_count{_render_labels(labels)} {values[len(_BUCKETS)]:g}")
                lines.append(f"{name}_sum{_render_labels(labels)} {values[-1]:g}")
        return "\n".join(lines) + "\n"


class Timer:
    def __init__(self) -> None:
        self.started = monotonic()

    def elapsed(self) -> float:
        return max(0.0, monotonic() - self.started)


def _labels(labels: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((key, value) for key, value in labels.items()))


def _render_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    rendered = ",".join(f'{key}="{_escape(value)}"' for key, value in labels)
    return "{" + rendered + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def error_class(status: int) -> str:
    if status < 400:
        return "none"
    if status < 500:
        return "4xx"
    return "5xx"


def finite_duration(value: float) -> float:
    return value if math.isfinite(value) and value >= 0 else 0.0
