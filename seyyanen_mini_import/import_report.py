"""
Seyyanen Mini PC Integration — Import Report
Detailed statistics, error accounting, and formatted summary generation.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Set, Tuple, Dict, Any


@dataclass
class MiniImportReport:
    source_path: str = ""
    session_id: str = "UNKNOWN"
    rows_read: int = 0
    rows_valid: int = 0
    rows_invalid: int = 0
    rows_dropped: int = 0
    duplicates: int = 0
    out_of_order: int = 0
    unique_pids: Set[str] = field(default_factory=set)
    valid_samples: int = 0
    failed_samples: int = 0
    timeouts: int = 0
    no_data: int = 0
    transport_errors: int = 0
    timestamp_start_us: int = 0
    timestamp_end_us: int = 0
    duration_s: float = 0.0
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    import_time_iso: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_path": self.source_path,
            "session_id": self.session_id,
            "rows_read": self.rows_read,
            "rows_valid": self.rows_valid,
            "rows_invalid": self.rows_invalid,
            "rows_dropped": self.rows_dropped,
            "duplicates": self.duplicates,
            "out_of_order": self.out_of_order,
            "unique_pids": sorted(list(self.unique_pids)),
            "valid_samples": self.valid_samples,
            "failed_samples": self.failed_samples,
            "timeouts": self.timeouts,
            "no_data": self.no_data,
            "transport_errors": self.transport_errors,
            "timestamp_start_us": self.timestamp_start_us,
            "timestamp_end_us": self.timestamp_end_us,
            "duration_s": round(self.duration_s, 3),
            "warnings_count": len(self.warnings),
            "errors_count": len(self.errors),
            "import_time_iso": self.import_time_iso,
        }

    def to_text(self) -> str:
        lines = [
            "==================================================",
            "        SEYYANEN MINI — IMPORT REPORT",
            "==================================================",
            f"Session ID:         {self.session_id}",
            f"Source Path:        {self.source_path}",
            f"Import Timestamp:   {self.import_time_iso}",
            f"Result:             {'SUCCESS' if len(self.errors) == 0 else 'FAILED'}",
            "--------------------------------------------------",
            "ROW ACCOUNTING:",
            f"  Total Rows Read:  {self.rows_read}",
            f"  Valid Rows:       {self.rows_valid}",
            f"  Invalid Rows:     {self.rows_invalid}",
            f"  Dropped Rows:     {self.rows_dropped}",
            f"  Duplicates:       {self.duplicates}",
            f"  Out of Order:     {self.out_of_order}",
            "--------------------------------------------------",
            "SIGNAL & ERROR STATISTICS:",
            f"  Unique PIDs ({len(self.unique_pids)}):  {', '.join(sorted(list(self.unique_pids))) if self.unique_pids else 'None'}",
            f"  Valid Measurements:{self.valid_samples}",
            f"  Failed Samples:   {self.failed_samples}",
            f"    - Timeouts:     {self.timeouts}",
            f"    - NO DATA:      {self.no_data}",
            f"    - Transport Err:{self.transport_errors}",
            "--------------------------------------------------",
            "TIME AXIS:",
            f"  Duration:         {self.duration_s:.2f} seconds",
            f"  Start (us):       {self.timestamp_start_us}",
            f"  End (us):         {self.timestamp_end_us}",
        ]

        if self.warnings:
            lines.append("--------------------------------------------------")
            lines.append(f"WARNINGS ({len(self.warnings)}):")
            for w in self.warnings[:10]:
                lines.append(f"  [WARN] {w}")
            if len(self.warnings) > 10:
                lines.append(f"  ... and {len(self.warnings) - 10} more warnings")

        if self.errors:
            lines.append("--------------------------------------------------")
            lines.append(f"ERRORS ({len(self.errors)}):")
            for e in self.errors[:15]:
                lines.append(f"  [ERROR] {e}")
            if len(self.errors) > 15:
                lines.append(f"  ... and {len(self.errors) - 15} more errors")

        lines.append("==================================================")
        return "\n".join(lines)
