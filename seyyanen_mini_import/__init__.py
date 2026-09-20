"""
Seyyanen Mini PC Integration Package
Phase M-8: Embedded Data Acquisition Companion Importer
"""

from .importer import (
    import_mini_session,
    preview_mini_session,
    attach_session_to_vehicle,
    handoff_to_c_layer,
    MiniImportResult,
    MiniSessionPreview,
)
from .metadata_parser import (
    MiniSessionMetadata,
    MiniAdapterInfo,
    MiniVehicleInfo,
    MiniSupportedPid,
)
from .mini_normalizer import (
    MiniObservation,
    ObservationProvenance,
)
from .import_report import (
    MiniImportReport,
)

__all__ = [
    "import_mini_session",
    "preview_mini_session",
    "attach_session_to_vehicle",
    "handoff_to_c_layer",
    "MiniImportResult",
    "MiniSessionPreview",
    "MiniObservation",
    "MiniSessionMetadata",
    "MiniAdapterInfo",
    "MiniVehicleInfo",
    "MiniSupportedPid",
    "ObservationProvenance",
    "MiniImportReport",
]

__version__ = "1.0.0"
