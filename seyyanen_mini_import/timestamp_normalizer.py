"""
Seyyanen Mini PC Integration — Timestamp Normalizer
Preserves original microsecond timestamps while creating a normalized, reversible PC time axis.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple


class TimestampNormalizer:
    """Provides reversible timestamp normalization and relative session time axis."""

    def __init__(self, t0_us: Optional[int] = None, base_iso_str: Optional[str] = None):
        self.t0_us: Optional[int] = t0_us
        self.base_datetime: Optional[datetime] = None
        if base_iso_str:
            self._parse_base_iso(base_iso_str)

    def _parse_base_iso(self, iso_str: str):
        try:
            # Handle ISO string with trailing Z or timezone offsets
            clean = iso_str.strip().replace("Z", "+00:00")
            self.base_datetime = datetime.fromisoformat(clean)
        except Exception:
            self.base_datetime = None

    def set_origin(self, first_sample_us: int):
        if self.t0_us is None:
            self.t0_us = first_sample_us

    def normalize(self, sample_ts_us: int) -> Tuple[float, Optional[str]]:
        """
        Returns:
          relative_time_s: float seconds relative to first sample (t0 = 0.0s)
          wall_clock_iso: Optional ISO 8601 string if base_iso was supplied
        """
        if self.t0_us is None:
            self.t0_us = sample_ts_us

        rel_s = (sample_ts_us - self.t0_us) / 1000000.0

        wall_clock_iso = None
        if self.base_datetime is not None:
            dt = self.base_datetime + timedelta(seconds=rel_s)
            wall_clock_iso = dt.isoformat()

        return rel_s, wall_clock_iso

    def denormalize(self, relative_time_s: float) -> int:
        """Reverses normalization back to approximate microsecond timestamp."""
        if self.t0_us is None:
            return 0
        return self.t0_us + int(round(relative_time_s * 1000000.0))
