# SPDX-License-Identifier: GPL-3.0-or-later
"""Rolling CPU-time statistics for the ``debug_timing`` pref (Phase 2).

``view.draw_manager.draw_callback`` measures each drawing callback with
``time.perf_counter()`` and calls :meth:`TimingStats.add` on ``state.timing`` when
``state.debug_timing`` is set; ``ops.plaza`` prints :meth:`TimingStats.summary` when the
session ends.

Pure Python (no bpy).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

DEFAULT_WINDOW = 120        # samples kept for the rolling (recent) figures


@dataclass(eq=False, slots=True)
class TimingStats:
    """Session totals plus a rolling window of the last ``window`` samples (seconds)."""

    window: int = DEFAULT_WINDOW
    count: int = 0
    total: float = 0.0
    max: float = 0.0
    _recent: deque = field(default_factory=deque, repr=False)

    def add(self, seconds: float) -> None:
        """Record one sample (negative values are clamped to 0)."""
        seconds = max(0.0, float(seconds))
        self.count += 1
        self.total += seconds
        if seconds > self.max:
            self.max = seconds
        self._recent.append(seconds)
        while len(self._recent) > max(1, self.window):
            self._recent.popleft()

    @property
    def avg(self) -> float:
        """Mean over the whole session (0.0 with no samples)."""
        return self.total / self.count if self.count else 0.0

    @property
    def recent_avg(self) -> float:
        """Mean over the rolling window (0.0 with no samples)."""
        return sum(self._recent) / len(self._recent) if self._recent else 0.0

    @property
    def recent_max(self) -> float:
        """Max over the rolling window (0.0 with no samples)."""
        return max(self._recent) if self._recent else 0.0

    def summary(self) -> dict[str, float]:
        """Plain-data summary in milliseconds: count, avg_ms, max_ms, recent_avg_ms,
        recent_max_ms (used in ``plaza.last_session()['timing']`` and the debug print)."""
        return {
            'count': self.count,
            'avg_ms': self.avg * 1000.0,
            'max_ms': self.max * 1000.0,
            'recent_avg_ms': self.recent_avg * 1000.0,
            'recent_max_ms': self.recent_max * 1000.0,
        }
