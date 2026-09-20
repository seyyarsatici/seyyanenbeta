"""
Seyyanen Mini PC Integration — Session Reader
Discovers, unpacks, and safely streams session files from directories or zip archives.
"""

import os
import zipfile
import tempfile
import shutil
from typing import Generator, Tuple, Optional, Dict, Any, List


class SessionReader:
    """Safely handles reading and streaming session files."""

    def __init__(self, target_path: str):
        self.target_path = os.path.abspath(target_path)
        self.extracted_dir: Optional[str] = None
        self.is_temp = False
        self.session_dir = ""
        self._resolve_path()

    def _resolve_path(self):
        if not os.path.exists(self.target_path):
            raise FileNotFoundError(f"Session path does not exist: {self.target_path}")

        if os.path.isfile(self.target_path):
            if self.target_path.lower().endswith(".zip"):
                self.is_temp = True
                self.extracted_dir = tempfile.mkdtemp(prefix="mini_import_")
                with zipfile.ZipFile(self.target_path, 'r') as zf:
                    # Guard against zip slip
                    for member in zf.infolist():
                        extracted_path = os.path.abspath(os.path.join(self.extracted_dir, member.filename))
                        if not extracted_path.startswith(os.path.abspath(self.extracted_dir)):
                            raise ValueError(f"Zip slip security violation in member: {member.filename}")
                    zf.extractall(self.extracted_dir)

                entries = os.listdir(self.extracted_dir)
                if len(entries) == 1 and os.path.isdir(os.path.join(self.extracted_dir, entries[0])):
                    self.session_dir = os.path.join(self.extracted_dir, entries[0])
                else:
                    self.session_dir = self.extracted_dir
            else:
                # If target is a file directly, e.g. session.csv, set parent as session dir
                self.session_dir = os.path.dirname(self.target_path)
        elif os.path.isdir(self.target_path):
            self.session_dir = self.target_path
        else:
            raise ValueError(f"Invalid target path: {self.target_path}")

    def get_metadata_path(self) -> Optional[str]:
        candidates = ["metadata.json", "meta.json"]
        for c in candidates:
            p = os.path.join(self.session_dir, c)
            if os.path.isfile(p):
                return p
        return None

    def get_csv_path(self) -> Optional[str]:
        candidates = ["session.csv", "samples.csv", "data.csv"]
        for c in candidates:
            p = os.path.join(self.session_dir, c)
            if os.path.isfile(p):
                return p
        # Check if there's any single .csv in directory
        csv_files = [f for f in os.listdir(self.session_dir) if f.lower().endswith(".csv")]
        if len(csv_files) == 1:
            return os.path.join(self.session_dir, csv_files[0])
        return None

    def get_events_path(self) -> Optional[str]:
        candidates = ["events.log", "events.txt"]
        for c in candidates:
            p = os.path.join(self.session_dir, c)
            if os.path.isfile(p):
                return p
        return None

    def stream_csv_lines(self) -> Generator[str, None, None]:
        csv_path = self.get_csv_path()
        if not csv_path or not os.path.isfile(csv_path):
            raise FileNotFoundError("session.csv file not found in session directory")

        with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                yield line

    def read_metadata_content(self) -> Optional[str]:
        meta_path = self.get_metadata_path()
        if not meta_path or not os.path.isfile(meta_path):
            return None
        with open(meta_path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()

    def read_events_content(self) -> Optional[str]:
        events_path = self.get_events_path()
        if not events_path or not os.path.isfile(events_path):
            return None
        with open(events_path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()

    def close(self):
        if self.is_temp and self.extracted_dir and os.path.exists(self.extracted_dir):
            shutil.rmtree(self.extracted_dir, ignore_errors=True)
            self.extracted_dir = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
