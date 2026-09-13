#!/usr/bin/env python3
"""
Seyyanen Automotive Diagnostic Platform — Phase J-2
===================================================
Multi-Platform Abstraction Layer
`platform_abstraction.py`

Architectural Role:
    Application & Presentation Layers
        ↓
    Platform Abstraction (Phase J-2: platform_abstraction.py)
        ↓
    Hardware / Adapter Abstraction (Phase J-1: diagnostic_adapter.py)
        ↓
    Diagnostic Transport & Protocols (Phases C → I)

Invariants Enforced:
1. C → I diagnostic intelligence and J-1 adapter abstractions remain strictly OS-agnostic.
2. Operating system differences are isolated below the diagnostic architecture.
3. Unsupported platforms fail closed with explicit UnsupportedPlatformError.
4. Path, data, cache, config, and log locations use standard platform conventions.
5. Device discovery abstracts Windows COM ports, Linux ttyUSB/ttyACM, and macOS cu.usbserial.
6. Communication and platform errors (permission, device missing) are never converted
   into vehicle ECU component defects (COMMUNICATION / PLATFORM FAILURE != COMPONENT FAILURE).
7. Platform layer never executes direct diagnostic commands or bypasses safety policies.
"""

from __future__ import annotations

import enum
import logging
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("seyyanen.platform")


# =====================================================================
# 1. TAXONOMY & ENUMS
# =====================================================================

class OSFamily(str, enum.Enum):
    """Supported and classified operating system families."""
    WINDOWS = "WINDOWS"
    LINUX = "LINUX"
    MACOS = "MACOS"
    UNSUPPORTED = "UNSUPPORTED"


class CPUArchitecture(str, enum.Enum):
    """Processor architectures."""
    X86_64 = "X86_64"
    ARM64 = "ARM64"
    X86_32 = "X86_32"
    ARM32 = "ARM32"
    UNKNOWN = "UNKNOWN"


# =====================================================================
# 2. STRUCTURED PLATFORM CAPABILITIES
# =====================================================================

@dataclass(frozen=True)
class PlatformCapabilities:
    """
    Explicit, auditable capabilities supported by the underlying platform runtime.
    Upper layers query these capabilities rather than guessing OS behavior.
    """
    supports_serial_enumeration: bool = True
    supports_usb_device_discovery: bool = True
    supports_raw_socketcan: bool = False      # Native SocketCAN on Linux
    supports_named_pipes: bool = False        # Windows named pipes
    supports_posix_permissions: bool = False  # POSIX mode flags & ownership
    supports_process_spawn: bool = True       # subprocess execution
    supports_desktop_launch: bool = True      # Opening PDFs / browser externally
    supports_bluetooth_rfcomm: bool = False   # Bluetooth SPP stack presence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "supports_serial_enumeration": self.supports_serial_enumeration,
            "supports_usb_device_discovery": self.supports_usb_device_discovery,
            "supports_raw_socketcan": self.supports_raw_socketcan,
            "supports_named_pipes": self.supports_named_pipes,
            "supports_posix_permissions": self.supports_posix_permissions,
            "supports_process_spawn": self.supports_process_spawn,
            "supports_desktop_launch": self.supports_desktop_launch,
            "supports_bluetooth_rfcomm": self.supports_bluetooth_rfcomm,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlatformCapabilities":
        return cls(
            supports_serial_enumeration=bool(data.get("supports_serial_enumeration", True)),
            supports_usb_device_discovery=bool(data.get("supports_usb_device_discovery", True)),
            supports_raw_socketcan=bool(data.get("supports_raw_socketcan", False)),
            supports_named_pipes=bool(data.get("supports_named_pipes", False)),
            supports_posix_permissions=bool(data.get("supports_posix_permissions", False)),
            supports_process_spawn=bool(data.get("supports_process_spawn", True)),
            supports_desktop_launch=bool(data.get("supports_desktop_launch", True)),
            supports_bluetooth_rfcomm=bool(data.get("supports_bluetooth_rfcomm", False)),
        )


# =====================================================================
# 3. STRUCTURED PLATFORM INFO
# =====================================================================

@dataclass(frozen=True)
class PlatformInfo:
    """Immutable snapshot of the executing platform environment."""
    os_family: OSFamily
    os_name: str
    os_version: str
    architecture: CPUArchitecture
    python_version: str
    hostname: str
    is_64bit: bool
    is_posix: bool
    is_windows: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "os_family": self.os_family.value,
            "os_name": self.os_name,
            "os_version": self.os_version,
            "architecture": self.architecture.value,
            "python_version": self.python_version,
            "hostname": self.hostname,
            "is_64bit": self.is_64bit,
            "is_posix": self.is_posix,
            "is_windows": self.is_windows,
        }


# =====================================================================
# 4. STRUCTURED PLATFORM ERROR MODEL
# =====================================================================

class PlatformError(Exception):
    """
    Base exception for all operating system and platform abstraction anomalies.
    Invariant: is_platform_error=True and is_communication_failure=True indicate
    that this is an OS or infrastructure issue, NEVER an ECU component defect.
    """
    def __init__(self, message: str, os_family: Optional[OSFamily] = None):
        super().__init__(message)
        self.message = message
        self.os_family = os_family
        self.is_platform_error = True
        self.is_communication_failure = True
        self.timestamp = time.time()

    def __str__(self) -> str:
        os_str = f"[{self.os_family.value}] " if self.os_family else ""
        return f"[{self.__class__.__name__}] {os_str}{self.message}"


class UnsupportedPlatformError(PlatformError):
    """Application attempted to execute on an unsupported operating system."""
    pass


class PlatformResourceUnavailableError(PlatformError):
    """A required system resource (serial port, directory, bus) is unavailable."""
    pass


class PlatformPermissionError(PlatformError):
    """Access denied by operating system (e.g. dialout group, elevated privilege)."""
    pass


class DeviceDiscoveryError(PlatformError):
    """Failed to enumerate or scan diagnostic adapter hardware interfaces."""
    pass


class ExecutableNotFoundError(PlatformError):
    """Requested external executable or viewer tool not found on system PATH."""
    pass


class PlatformConfigurationError(PlatformError):
    """Platform environment or configuration directory structure is invalid."""
    pass


# =====================================================================
# 5. PLATFORM PROVIDER (STRATEGY & TEST DOUBLE EXTENSION POINT)
# =====================================================================

class IPlatformProvider:
    """Interface for platform environment detection, paths, and OS interactions."""
    def get_platform_info(self) -> PlatformInfo:
        raise NotImplementedError

    def get_capabilities(self) -> PlatformCapabilities:
        raise NotImplementedError

    def get_app_data_dir(self, app_name: str = "seyyanen") -> Path:
        raise NotImplementedError

    def get_config_dir(self, app_name: str = "seyyanen") -> Path:
        raise NotImplementedError

    def get_cache_dir(self, app_name: str = "seyyanen") -> Path:
        raise NotImplementedError

    def get_log_dir(self, app_name: str = "seyyanen") -> Path:
        raise NotImplementedError

    def get_temp_dir(self, app_name: str = "seyyanen") -> Path:
        raise NotImplementedError

    def enumerate_serial_ports(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def find_executable(self, name: str) -> Optional[Path]:
        raise NotImplementedError

    def open_document(self, document_path: Path) -> bool:
        raise NotImplementedError


# =====================================================================
# 6. DEFAULT LIVE PLATFORM PROVIDER
# =====================================================================

class DefaultPlatformProvider(IPlatformProvider):
    """
    Production platform provider querying live Python runtime,
    operating system environment, and filesystem.
    """
    def __init__(self, repo_root: Optional[Path] = None):
        self._repo_root = repo_root or Path(__file__).resolve().parent

    def get_platform_info(self) -> PlatformInfo:
        sys_plat = sys.platform.lower()
        if sys_plat.startswith("win"):
            os_fam = OSFamily.WINDOWS
        elif sys_plat.startswith("linux"):
            os_fam = OSFamily.LINUX
        elif sys_plat.startswith("darwin"):
            os_fam = OSFamily.MACOS
        else:
            os_fam = OSFamily.UNSUPPORTED

        mach = platform.machine().lower()
        if mach in ("x86_64", "amd64"):
            arch = CPUArchitecture.X86_64
        elif mach in ("arm64", "aarch64"):
            arch = CPUArchitecture.ARM64
        elif mach in ("i386", "i686", "x86"):
            arch = CPUArchitecture.X86_32
        elif mach.startswith("arm"):
            arch = CPUArchitecture.ARM32
        else:
            arch = CPUArchitecture.UNKNOWN

        return PlatformInfo(
            os_family=os_fam,
            os_name=platform.system(),
            os_version=platform.version(),
            architecture=arch,
            python_version=platform.python_version(),
            hostname=platform.node(),
            is_64bit=sys.maxsize > 2**32,
            is_posix=os.name == "posix",
            is_windows=os.name == "nt",
        )

    def get_capabilities(self) -> PlatformCapabilities:
        info = self.get_platform_info()
        is_win = info.os_family == OSFamily.WINDOWS
        is_linux = info.os_family == OSFamily.LINUX
        is_mac = info.os_family == OSFamily.MACOS

        return PlatformCapabilities(
            supports_serial_enumeration=True,
            supports_usb_device_discovery=True,
            supports_raw_socketcan=is_linux,
            supports_named_pipes=is_win,
            supports_posix_permissions=info.is_posix,
            supports_process_spawn=True,
            supports_desktop_launch=is_win or is_linux or is_mac,
            supports_bluetooth_rfcomm=False,  # Kept explicitly False until RFCOMM stack implemented
        )

    # -----------------------------------------------------------------
    # Filesystem & Path Management
    # -----------------------------------------------------------------

    def get_app_data_dir(self, app_name: str = "seyyanen") -> Path:
        info = self.get_platform_info()
        if info.os_family == OSFamily.WINDOWS:
            base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or (Path.home() / "AppData" / "Local")
            return Path(base) / app_name
        elif info.os_family == OSFamily.MACOS:
            return Path.home() / "Library" / "Application Support" / app_name
        else:  # Linux / POSIX fallback
            xdg_data = os.environ.get("XDG_DATA_HOME")
            base = Path(xdg_data) if xdg_data else (Path.home() / ".local" / "share")
            return base / app_name

    def get_config_dir(self, app_name: str = "seyyanen") -> Path:
        info = self.get_platform_info()
        if info.os_family == OSFamily.WINDOWS:
            base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
            return Path(base) / app_name
        elif info.os_family == OSFamily.MACOS:
            return Path.home() / "Library" / "Preferences" / app_name
        else:  # Linux / POSIX fallback
            xdg_config = os.environ.get("XDG_CONFIG_HOME")
            base = Path(xdg_config) if xdg_config else (Path.home() / ".config")
            return base / app_name

    def get_cache_dir(self, app_name: str = "seyyanen") -> Path:
        info = self.get_platform_info()
        if info.os_family == OSFamily.WINDOWS:
            base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
            return Path(base) / app_name / "Cache"
        elif info.os_family == OSFamily.MACOS:
            return Path.home() / "Library" / "Caches" / app_name
        else:  # Linux / POSIX fallback
            xdg_cache = os.environ.get("XDG_CACHE_HOME")
            base = Path(xdg_cache) if xdg_cache else (Path.home() / ".cache")
            return base / app_name

    def get_log_dir(self, app_name: str = "seyyanen") -> Path:
        info = self.get_platform_info()
        if info.os_family == OSFamily.WINDOWS:
            return self.get_app_data_dir(app_name) / "Logs"
        elif info.os_family == OSFamily.MACOS:
            return Path.home() / "Library" / "Logs" / app_name
        else:
            xdg_state = os.environ.get("XDG_STATE_HOME")
            base = Path(xdg_state) if xdg_state else (Path.home() / ".local" / "state")
            return base / app_name / "logs"

    def get_temp_dir(self, app_name: str = "seyyanen") -> Path:
        return Path(tempfile.gettempdir()) / app_name

    # -----------------------------------------------------------------
    # Device Discovery & Enumeration
    # -----------------------------------------------------------------

    def enumerate_serial_ports(self) -> List[Dict[str, Any]]:
        """
        Discovers serial and USB-to-serial ports on the current platform.
        Uses pyserial list_ports if installed, otherwise safely falls back.
        """
        results: List[Dict[str, Any]] = []
        try:
            from serial.tools import list_ports
            for p in list_ports.comports():
                results.append({
                    "device": p.device,
                    "name": getattr(p, "name", p.device),
                    "description": getattr(p, "description", ""),
                    "manufacturer": getattr(p, "manufacturer", None),
                    "hwid": getattr(p, "hwid", ""),
                    "vid": getattr(p, "vid", None),
                    "pid": getattr(p, "pid", None),
                    "serial_number": getattr(p, "serial_number", None),
                })
        except ImportError:
            logger.warning("pyserial list_ports not installed; serial enumeration limited.")
        except Exception as e:
            raise DeviceDiscoveryError(f"Serial port enumeration failed on host: {e}") from e

        return results

    # -----------------------------------------------------------------
    # Executable Discovery & Launch
    # -----------------------------------------------------------------

    def find_executable(self, name: str) -> Optional[Path]:
        found = shutil.which(name)
        return Path(found) if found else None

    def open_document(self, document_path: Path) -> bool:
        """Opens a generated report or document safely via system default handler."""
        if not document_path.exists():
            raise FileNotFoundError(f"Document does not exist: {document_path}")

        info = self.get_platform_info()
        try:
            if info.os_family == OSFamily.WINDOWS:
                os.startfile(str(document_path))
                return True
            elif info.os_family == OSFamily.MACOS:
                subprocess.Popen(["open", str(document_path)])
                return True
            elif info.os_family == OSFamily.LINUX:
                subprocess.Popen(["xdg-open", str(document_path)])
                return True
            else:
                raise UnsupportedPlatformError(f"Document opening not supported on {info.os_family.value}.")
        except Exception as e:
            logger.error("Failed to open document '%s': %s", document_path, e)
            return False


# =====================================================================
# 7. SIMULATED PLATFORM PROVIDER (TEST DOUBLE)
# =====================================================================

class SimulatedPlatformProvider(IPlatformProvider):
    """
    Deterministic Test Double for verifying cross-platform logic
    (Windows, Linux, macOS, or Unsupported) on any build machine.
    """
    def __init__(
        self,
        os_family: OSFamily = OSFamily.LINUX,
        architecture: CPUArchitecture = CPUArchitecture.X86_64,
        simulated_home: Optional[Path] = None,
        custom_capabilities: Optional[PlatformCapabilities] = None,
        simulated_ports: Optional[List[Dict[str, Any]]] = None,
    ):
        self.os_family = os_family
        self.architecture = architecture
        self.home = simulated_home or Path("/home/mockuser" if os_family != OSFamily.WINDOWS else "C:/Users/mockuser")
        self.custom_capabilities = custom_capabilities
        self.simulated_ports = list(simulated_ports or [])
        self.opened_documents: List[Path] = []
        self.executables: Dict[str, Path] = {}

    def get_platform_info(self) -> PlatformInfo:
        return PlatformInfo(
            os_family=self.os_family,
            os_name="Simulated-" + self.os_family.value,
            os_version="1.0.0-mock",
            architecture=self.architecture,
            python_version="3.12.0",
            hostname="seyyanen-sim-host",
            is_64bit=True,
            is_posix=self.os_family in (OSFamily.LINUX, OSFamily.MACOS),
            is_windows=self.os_family == OSFamily.WINDOWS,
        )

    def get_capabilities(self) -> PlatformCapabilities:
        if self.custom_capabilities:
            return self.custom_capabilities

        is_win = self.os_family == OSFamily.WINDOWS
        is_linux = self.os_family == OSFamily.LINUX
        is_mac = self.os_family == OSFamily.MACOS

        return PlatformCapabilities(
            supports_serial_enumeration=True,
            supports_usb_device_discovery=True,
            supports_raw_socketcan=is_linux,
            supports_named_pipes=is_win,
            supports_posix_permissions=is_linux or is_mac,
            supports_process_spawn=True,
            supports_desktop_launch=is_win or is_linux or is_mac,
            supports_bluetooth_rfcomm=False,
        )

    def get_app_data_dir(self, app_name: str = "seyyanen") -> Path:
        if self.os_family == OSFamily.WINDOWS:
            return self.home / "AppData" / "Local" / app_name
        elif self.os_family == OSFamily.MACOS:
            return self.home / "Library" / "Application Support" / app_name
        else:
            return self.home / ".local" / "share" / app_name

    def get_config_dir(self, app_name: str = "seyyanen") -> Path:
        if self.os_family == OSFamily.WINDOWS:
            return self.home / "AppData" / "Roaming" / app_name
        elif self.os_family == OSFamily.MACOS:
            return self.home / "Library" / "Preferences" / app_name
        else:
            return self.home / ".config" / app_name

    def get_cache_dir(self, app_name: str = "seyyanen") -> Path:
        if self.os_family == OSFamily.WINDOWS:
            return self.home / "AppData" / "Local" / app_name / "Cache"
        elif self.os_family == OSFamily.MACOS:
            return self.home / "Library" / "Caches" / app_name
        else:
            return self.home / ".cache" / app_name

    def get_log_dir(self, app_name: str = "seyyanen") -> Path:
        if self.os_family == OSFamily.WINDOWS:
            return self.get_app_data_dir(app_name) / "Logs"
        elif self.os_family == OSFamily.MACOS:
            return self.home / "Library" / "Logs" / app_name
        else:
            return self.home / ".local" / "state" / app_name / "logs"

    def get_temp_dir(self, app_name: str = "seyyanen") -> Path:
        base = Path("C:/Windows/Temp" if self.os_family == OSFamily.WINDOWS else "/tmp")
        return base / app_name

    def enumerate_serial_ports(self) -> List[Dict[str, Any]]:
        return list(self.simulated_ports)

    def find_executable(self, name: str) -> Optional[Path]:
        return self.executables.get(name)

    def open_document(self, document_path: Path) -> bool:
        if self.os_family == OSFamily.UNSUPPORTED:
            raise UnsupportedPlatformError(f"Document opening not supported on {self.os_family.value}.")
        self.opened_documents.append(document_path)
        return True


# =====================================================================
# 8. PLATFORM MANAGER (CANONICAL FACADE)
# =====================================================================

class PlatformManager:
    """
    Primary Platform Facade for the Seyyanen platform.
    Manages platform queries, standard paths, device discovery,
    and platform capability checks with dependency-injection support.
    """
    _current_provider: IPlatformProvider = DefaultPlatformProvider()

    @classmethod
    def set_provider(cls, provider: IPlatformProvider) -> None:
        """Injects a custom or simulated platform provider (e.g. for testing)."""
        cls._current_provider = provider
        logger.info("PlatformManager provider set to '%s'.", provider.__class__.__name__)

    @classmethod
    def reset_to_default_provider(cls) -> None:
        """Restores the live host default provider."""
        cls._current_provider = DefaultPlatformProvider()

    @classmethod
    def get_provider(cls) -> IPlatformProvider:
        return cls._current_provider

    @classmethod
    def get_info(cls) -> PlatformInfo:
        return cls._current_provider.get_platform_info()

    @classmethod
    def get_capabilities(cls) -> PlatformCapabilities:
        return cls._current_provider.get_capabilities()

    @classmethod
    def require_capability(cls, capability_name: str) -> None:
        """Enforces that the current platform supports the required capability."""
        caps = cls.get_capabilities()
        if not getattr(caps, capability_name, False):
            raise PlatformResourceUnavailableError(
                f"Platform '{cls.get_info().os_family.value}' lacks capability '{capability_name}'."
            )

    @classmethod
    def ensure_supported_platform(cls) -> None:
        """Verifies that the current platform is supported by Seyyanen."""
        info = cls.get_info()
        if info.os_family == OSFamily.UNSUPPORTED:
            raise UnsupportedPlatformError(
                f"Operating system '{info.os_name}' ({info.os_version}) is currently unsupported by Seyyanen."
            )

    # -----------------------------------------------------------------
    # Canonical Paths
    # -----------------------------------------------------------------

    @classmethod
    def get_app_data_path(cls, filename: Optional[str] = None) -> Path:
        p = cls._current_provider.get_app_data_dir()
        return (p / filename) if filename else p

    @classmethod
    def get_config_path(cls, filename: Optional[str] = None) -> Path:
        p = cls._current_provider.get_config_dir()
        return (p / filename) if filename else p

    @classmethod
    def get_cache_path(cls, filename: Optional[str] = None) -> Path:
        p = cls._current_provider.get_cache_dir()
        return (p / filename) if filename else p

    @classmethod
    def get_log_path(cls, filename: Optional[str] = None) -> Path:
        p = cls._current_provider.get_log_dir()
        return (p / filename) if filename else p

    @classmethod
    def get_temp_path(cls, filename: Optional[str] = None) -> Path:
        p = cls._current_provider.get_temp_dir()
        return (p / filename) if filename else p

    # -----------------------------------------------------------------
    # Cross-Platform Device Discovery
    # -----------------------------------------------------------------

    @classmethod
    def discover_diagnostic_devices(
        cls,
        keywords: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Discovers serial and USB diagnostic adapters matching known VCI signatures.
        Works across Windows COM ports, Linux ttyUSB/ttyACM, and macOS cu.usbserial.
        """
        raw_ports = cls._current_provider.enumerate_serial_ports()
        vci_keywords = [k.lower() for k in (keywords or ["vlinker", "ch340", "ftdi", "elm327", "obd", "cp210", "prolific"])]

        matched: List[Dict[str, Any]] = []
        for port in raw_ports:
            dev_str = str(port.get("device", "")).lower()
            desc_str = (str(port.get("description", "")) + " " + str(port.get("manufacturer", ""))).lower()

            is_match = any(kw in desc_str or kw in dev_str for kw in vci_keywords)
            matched.append({
                "device": port.get("device"),
                "description": port.get("description"),
                "is_likely_vci": is_match,
                "vid": port.get("vid"),
                "pid": port.get("pid"),
                "manufacturer": port.get("manufacturer"),
            })

        return matched

    @classmethod
    def get_default_diagnostic_port(cls) -> Optional[str]:
        """Returns the most likely diagnostic adapter port, or None if not found."""
        devices = cls.discover_diagnostic_devices()
        likely = [d["device"] for d in devices if d.get("is_likely_vci")]
        if likely:
            return likely[0]
        if devices:
            return devices[0]["device"]
        return None

    @classmethod
    def find_executable(cls, name: str) -> Optional[Path]:
        """Discovers executable path on system PATH via active provider."""
        return cls._current_provider.find_executable(name)

    @classmethod
    def open_document(cls, document_path: Path | str) -> bool:
        """Opens a document safely via active provider."""
        path_obj = Path(document_path) if isinstance(document_path, str) else document_path
        return cls._current_provider.open_document(path_obj)

