"""
Seyyanen Mini PC Integration — Metadata Parser
Parses and validates metadata.json according to the M-5 / M-7 specification.
"""

import json
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple


@dataclass
class MiniAdapterInfo:
    brand: str = "UNKNOWN"
    adapter_name: str = "UNKNOWN"
    manufacturer: str = "UNKNOWN"
    model: str = "UNKNOWN"
    firmware: str = "UNKNOWN"
    raw_identity: str = "UNKNOWN"
    remote_mac: str = "N/A"
    transport: str = "BLUETOOTH_SPP"
    verified: bool = False


@dataclass
class MiniSupportedPid:
    pid: str
    name: str
    unit: str
    priority: int = 1
    poll_interval_ms: int = 500
    supported: bool = True


@dataclass
class MiniVehicleInfo:
    make: str = "UNKNOWN"
    model: str = "UNKNOWN"
    engine: str = "UNKNOWN"
    ecu: str = "UNKNOWN"
    vin: Optional[str] = None
    vehicle_identity_status: str = "UNKNOWN"


@dataclass
class MiniSessionMetadata:
    session_id: str = "UNKNOWN"
    firmware_version: str = "UNKNOWN"
    mini_protocol_version: str = "1.0"
    session_state: str = "UNKNOWN"
    start_time_iso: Optional[str] = None
    end_time_iso: Optional[str] = None
    duration_seconds: float = 0.0
    sample_count: int = 0
    frame_count: int = 0
    error_count: int = 0
    protocol: str = "UNKNOWN"
    adapter: MiniAdapterInfo = field(default_factory=MiniAdapterInfo)
    vehicle: MiniVehicleInfo = field(default_factory=MiniVehicleInfo)
    supported_pids: List[MiniSupportedPid] = field(default_factory=list)
    storage_info: Dict[str, Any] = field(default_factory=dict)
    raw_dict: Dict[str, Any] = field(default_factory=dict)


class MetadataParser:
    """Parses raw JSON string into MiniSessionMetadata."""

    @staticmethod
    def parse(json_str: Optional[str]) -> Tuple[Optional[MiniSessionMetadata], List[str]]:
        errors: List[str] = []
        if not json_str or not json_str.strip():
            return None, ["MISSING_METADATA: metadata.json content is empty or file missing"]

        try:
            data = json.loads(json_str)
        except Exception as e:
            return None, [f"INVALID_METADATA: Failed to parse JSON: {str(e)}"]

        if not isinstance(data, dict):
            return None, ["INVALID_METADATA: Root metadata must be a JSON object"]

        meta = MiniSessionMetadata(raw_dict=data)

        # Core required keys
        if "session_id" not in data or not str(data["session_id"]).strip():
            errors.append("INVALID_METADATA: Missing or empty 'session_id'")
        else:
            meta.session_id = str(data["session_id"]).strip()

        meta.firmware_version = str(data.get("firmware_version", "UNKNOWN"))
        meta.mini_protocol_version = str(data.get("mini_protocol_version", "1.0"))
        meta.session_state = str(data.get("session_state", "UNKNOWN")).upper()
        meta.start_time_iso = data.get("start_time_iso")
        meta.end_time_iso = data.get("end_time_iso")
        meta.duration_seconds = float(data.get("duration_seconds", 0.0))
        meta.sample_count = int(data.get("sample_count", 0))
        meta.frame_count = int(data.get("frame_count", 0))
        meta.error_count = int(data.get("error_count", 0))
        meta.protocol = str(data.get("protocol", "UNKNOWN"))

        # Adapter info
        ad_data = data.get("adapter_identity", {})
        if isinstance(ad_data, dict):
            meta.adapter = MiniAdapterInfo(
                brand=str(ad_data.get("brand", "UNKNOWN")),
                adapter_name=str(ad_data.get("adapter_name", "UNKNOWN")),
                manufacturer=str(ad_data.get("manufacturer", "UNKNOWN")),
                model=str(ad_data.get("model", "UNKNOWN")),
                firmware=str(ad_data.get("firmware", "UNKNOWN")),
                raw_identity=str(ad_data.get("raw_identity", "UNKNOWN")),
                remote_mac=str(ad_data.get("remote_mac", "N/A")),
                transport=str(ad_data.get("transport", "BLUETOOTH_SPP")),
                verified=bool(ad_data.get("verified", False)),
            )

        # Vehicle info
        v_data = data.get("vehicle_info", {})
        if isinstance(v_data, dict):
            vin_val = v_data.get("vin")
            vin_status = "CONFIRMED" if (vin_val and len(vin_val) == 17) else "UNKNOWN"
            meta.vehicle = MiniVehicleInfo(
                make=str(v_data.get("make", "UNKNOWN")),
                model=str(v_data.get("model", "UNKNOWN")),
                engine=str(v_data.get("engine", "UNKNOWN")),
                ecu=str(v_data.get("ecu", "UNKNOWN")),
                vin=vin_val,
                vehicle_identity_status=vin_status,
            )
        else:
            meta.vehicle = MiniVehicleInfo(vehicle_identity_status="UNKNOWN")

        # Supported PIDs list
        pids_list = data.get("supported_pids", [])
        if isinstance(pids_list, list):
            for item in pids_list:
                if isinstance(item, dict) and "pid" in item:
                    meta.supported_pids.append(
                        MiniSupportedPid(
                            pid=str(item.get("pid", "")).upper(),
                            name=str(item.get("name", "")),
                            unit=str(item.get("unit", "")),
                            priority=int(item.get("priority", 1)),
                            poll_interval_ms=int(item.get("poll_interval_ms", 500)),
                            supported=bool(item.get("supported", True)),
                        )
                    )

        meta.storage_info = data.get("storage_info", {})

        return meta, errors
