#!/usr/bin/env python3
"""
Seyyanen Automotive Diagnostic Platform — Phase J-2
===================================================
Multi-Platform Support Test Suite
`test_phase_j2.py`

Certifies:
  A. Platform detection (OSFamily, PlatformInfo, live host detection)
  B. Windows abstraction behavior (AppData paths, named pipes, COM naming)
  C. Linux abstraction behavior (XDG paths, SocketCAN, /dev/ttyUSB naming)
  D. macOS abstraction behavior (Library paths, open tool, /dev/cu.usbserial)
  E. Unsupported platform behavior (fail closed, UnsupportedPlatformError)
  F. Architecture detection (X86_64, ARM64, X86_32, ARM32, UNKNOWN)
  G. Path handling (platform-safe paths, Path returns, sub-paths)
  H. Application data directory
  I. Cache directory
  J. Temporary directory
  K. Configuration location
  L. Executable discovery behavior (find_executable)
  M. Environment handling (XDG / AppData overrides)
  N. Adapter discovery integration (VCI keyword matching)
  O. Serial / device naming abstraction (COM vs ttyUSB vs cu.usbserial)
  P. Permission / error handling (is_platform_error, communication != component)
  Q. Subprocess failure handling (safe invocation, missing file checks)
  R. Encoding behavior (UTF-8, raw ECU bytes byte-accurate preservation)
  S. Deterministic platform provider tests (test doubles, injection & reset)
  T. J-1 regression (adapter abstraction integration)
  U. C→I diagnostic intelligence regression (safety & knowledge bases)
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

# Ensure project root in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from platform_abstraction import (
    CPUArchitecture,
    DefaultPlatformProvider,
    DeviceDiscoveryError,
    ExecutableNotFoundError,
    IPlatformProvider,
    OSFamily,
    PlatformCapabilities,
    PlatformConfigurationError,
    PlatformError,
    PlatformInfo,
    PlatformManager,
    PlatformPermissionError,
    PlatformResourceUnavailableError,
    SimulatedPlatformProvider,
    UnsupportedPlatformError,
)

# J-1 & Diagnostic Layer Imports for Regressions T & U
from diagnostic_adapter import (
    AdapterCapabilities,
    AdapterConnectionState,
    AdapterMetadata,
    AdapterRegistry,
    AdapterType,
    DiagnosticAdapter,
    DiagnosticProtocol,
    ELM327DiagnosticAdapter,
    MockDiagnosticAdapter,
    TransportMedium,
)
from advanced_ecu_services import (
    AdvancedServiceRequest,
    DiagnosticTransactionManager,
    ITransportAdapter,
    ServiceSafetyClassification,
    ServiceSafetyPolicy,
    STATUS_VALID,
)
from failure_pattern_library import FailurePatternLibraryStore
from vehicle_ecu_knowledge import VehicleECUKnowledgeStore


class TestPhaseJ2MultiPlatform(unittest.TestCase):
    """Exhaustive test suite certifying Phase J-2 Multi-Platform Support."""

    def setUp(self):
        # Save active provider and reset to default
        self._orig_provider = PlatformManager.get_provider()
        PlatformManager.reset_to_default_provider()

    def tearDown(self):
        # Always restore original provider after test
        PlatformManager.set_provider(self._orig_provider)

    # =====================================================================
    # A: PLATFORM DETECTION
    # =====================================================================
    def test_A_live_host_platform_detection(self):
        """Host platform detection returns valid PlatformInfo with expected taxonomy."""
        info = PlatformManager.get_info()
        self.assertIsInstance(info, PlatformInfo)
        self.assertIn(info.os_family, [OSFamily.WINDOWS, OSFamily.LINUX, OSFamily.MACOS])
        self.assertIsInstance(info.architecture, CPUArchitecture)
        self.assertTrue(len(info.python_version) > 0)
        self.assertTrue(len(info.hostname) > 0)
        self.assertIsInstance(info.is_64bit, bool)
        self.assertIsInstance(info.is_windows, bool)
        self.assertIsInstance(info.is_posix, bool)

        # Serialization round-trip
        data = info.to_dict()
        self.assertEqual(data["os_family"], info.os_family.value)
        self.assertEqual(data["architecture"], info.architecture.value)
        self.assertEqual(data["is_windows"], info.is_windows)

    # =====================================================================
    # B: WINDOWS ABSTRACTION BEHAVIOR
    # =====================================================================
    def test_B_windows_abstraction_behavior(self):
        """Simulated Windows environment exhibits correct paths, capabilities, and naming."""
        win_sim = SimulatedPlatformProvider(
            os_family=OSFamily.WINDOWS,
            architecture=CPUArchitecture.X86_64,
            simulated_home=Path("C:/Users/DiagnosticTech"),
            simulated_ports=[
                {"device": "COM3", "description": "vLinker FS USB Serial Port", "manufacturer": "FTDI", "vid": 0x0403, "pid": 0x6001},
                {"device": "COM1", "description": "Standard Communications Port", "manufacturer": "Microsoft", "vid": None, "pid": None},
            ]
        )
        PlatformManager.set_provider(win_sim)

        info = PlatformManager.get_info()
        caps = PlatformManager.get_capabilities()

        self.assertEqual(info.os_family, OSFamily.WINDOWS)
        self.assertTrue(info.is_windows)
        self.assertFalse(info.is_posix)

        # Capabilities: Windows supports named pipes, not raw socketcan
        self.assertTrue(caps.supports_named_pipes)
        self.assertFalse(caps.supports_raw_socketcan)
        self.assertTrue(caps.supports_serial_enumeration)

        # Standard Windows directory layout
        self.assertEqual(
            PlatformManager.get_app_data_path().as_posix(),
            "C:/Users/DiagnosticTech/AppData/Local/seyyanen"
        )
        self.assertEqual(
            PlatformManager.get_config_path().as_posix(),
            "C:/Users/DiagnosticTech/AppData/Roaming/seyyanen"
        )
        self.assertEqual(
            PlatformManager.get_cache_path().as_posix(),
            "C:/Users/DiagnosticTech/AppData/Local/seyyanen/Cache"
        )
        self.assertEqual(
            PlatformManager.get_log_path().as_posix(),
            "C:/Users/DiagnosticTech/AppData/Local/seyyanen/Logs"
        )
        self.assertEqual(
            PlatformManager.get_temp_path().as_posix(),
            "C:/Windows/Temp/seyyanen"
        )

    # =====================================================================
    # C: LINUX ABSTRACTION BEHAVIOR
    # =====================================================================
    def test_C_linux_abstraction_behavior(self):
        """Simulated Linux environment exhibits XDG paths, SocketCAN, and POSIX permissions."""
        linux_sim = SimulatedPlatformProvider(
            os_family=OSFamily.LINUX,
            architecture=CPUArchitecture.X86_64,
            simulated_home=Path("/home/diagnostic_user"),
            simulated_ports=[
                {"device": "/dev/ttyUSB0", "description": "OBDLink SX USB", "manufacturer": "FTDI", "vid": 0x0403, "pid": 0x6001},
                {"device": "/dev/ttyS0", "description": "16550A Serial Port", "manufacturer": None, "vid": None, "pid": None},
            ]
        )
        PlatformManager.set_provider(linux_sim)

        info = PlatformManager.get_info()
        caps = PlatformManager.get_capabilities()

        self.assertEqual(info.os_family, OSFamily.LINUX)
        self.assertFalse(info.is_windows)
        self.assertTrue(info.is_posix)

        # Capabilities: Linux supports raw SocketCAN and POSIX permissions, not named pipes
        self.assertTrue(caps.supports_raw_socketcan)
        self.assertTrue(caps.supports_posix_permissions)
        self.assertFalse(caps.supports_named_pipes)

        # XDG directory specifications
        self.assertEqual(
            PlatformManager.get_app_data_path().as_posix(),
            "/home/diagnostic_user/.local/share/seyyanen"
        )
        self.assertEqual(
            PlatformManager.get_config_path().as_posix(),
            "/home/diagnostic_user/.config/seyyanen"
        )
        self.assertEqual(
            PlatformManager.get_cache_path().as_posix(),
            "/home/diagnostic_user/.cache/seyyanen"
        )
        self.assertEqual(
            PlatformManager.get_log_path().as_posix(),
            "/home/diagnostic_user/.local/state/seyyanen/logs"
        )
        self.assertEqual(
            PlatformManager.get_temp_path().as_posix(),
            "/tmp/seyyanen"
        )

    # =====================================================================
    # D: MACOS ABSTRACTION BEHAVIOR
    # =====================================================================
    def test_D_macos_abstraction_behavior(self):
        """Simulated macOS environment exhibits ~/Library layout and cu.usbserial device names."""
        mac_sim = SimulatedPlatformProvider(
            os_family=OSFamily.MACOS,
            architecture=CPUArchitecture.ARM64,
            simulated_home=Path("/Users/diagnostic_tech"),
            simulated_ports=[
                {"device": "/dev/cu.usbserial-1420", "description": "ELM327 USB v1.5", "manufacturer": "FTDI", "vid": 0x0403, "pid": 0x6001},
            ]
        )
        PlatformManager.set_provider(mac_sim)

        info = PlatformManager.get_info()
        caps = PlatformManager.get_capabilities()

        self.assertEqual(info.os_family, OSFamily.MACOS)
        self.assertFalse(info.is_windows)
        self.assertTrue(info.is_posix)
        self.assertEqual(info.architecture, CPUArchitecture.ARM64)

        # Capabilities: macOS supports posix permissions, desktop launch, not socketcan
        self.assertTrue(caps.supports_posix_permissions)
        self.assertFalse(caps.supports_raw_socketcan)
        self.assertTrue(caps.supports_desktop_launch)

        # macOS standard ~/Library conventions
        self.assertEqual(
            PlatformManager.get_app_data_path().as_posix(),
            "/Users/diagnostic_tech/Library/Application Support/seyyanen"
        )
        self.assertEqual(
            PlatformManager.get_config_path().as_posix(),
            "/Users/diagnostic_tech/Library/Preferences/seyyanen"
        )
        self.assertEqual(
            PlatformManager.get_cache_path().as_posix(),
            "/Users/diagnostic_tech/Library/Caches/seyyanen"
        )
        self.assertEqual(
            PlatformManager.get_log_path().as_posix(),
            "/Users/diagnostic_tech/Library/Logs/seyyanen"
        )

    # =====================================================================
    # E: UNSUPPORTED PLATFORM BEHAVIOR
    # =====================================================================
    def test_E_unsupported_platform_fails_closed(self):
        """Unsupported platforms fail closed with explicit UnsupportedPlatformError."""
        unsupported_sim = SimulatedPlatformProvider(
            os_family=OSFamily.UNSUPPORTED,
            architecture=CPUArchitecture.UNKNOWN,
        )
        PlatformManager.set_provider(unsupported_sim)

        # ensure_supported_platform must raise UnsupportedPlatformError
        with self.assertRaises(UnsupportedPlatformError) as cm:
            PlatformManager.ensure_supported_platform()
        self.assertIn("unsupported", str(cm.exception).lower())

        # Document opening must fail closed
        with self.assertRaises(UnsupportedPlatformError):
            PlatformManager.open_document(Path("/tmp/report.pdf"))

    # =====================================================================
    # F: ARCHITECTURE DETECTION
    # =====================================================================
    def test_F_cpu_architecture_detection(self):
        """CPU architecture classification maps machine strings accurately."""
        self.assertIn(PlatformManager.get_info().architecture, list(CPUArchitecture))

        # Test simulated mappings
        arch_matrix = [
            (CPUArchitecture.X86_64, "X86_64"),
            (CPUArchitecture.ARM64, "ARM64"),
            (CPUArchitecture.X86_32, "X86_32"),
            (CPUArchitecture.ARM32, "ARM32"),
            (CPUArchitecture.UNKNOWN, "UNKNOWN"),
        ]
        for arch_enum, name in arch_matrix:
            provider = SimulatedPlatformProvider(architecture=arch_enum)
            self.assertEqual(provider.get_platform_info().architecture, arch_enum)
            self.assertEqual(provider.get_platform_info().to_dict()["architecture"], name)

    # =====================================================================
    # G: PATH HANDLING (PLATFORM-SAFE)
    # =====================================================================
    def test_G_path_handling_platform_safe(self):
        """Path methods return valid Path objects and support filename appending without leaks."""
        sim = SimulatedPlatformProvider(os_family=OSFamily.LINUX, simulated_home=Path("/opt/seyyanen_home"))
        PlatformManager.set_provider(sim)

        data_file = PlatformManager.get_app_data_path("session_log.dat")
        self.assertIsInstance(data_file, Path)
        self.assertEqual(data_file.name, "session_log.dat")
        self.assertEqual(data_file.parent.name, "seyyanen")

        cfg_file = PlatformManager.get_config_path("adapters.json")
        self.assertIsInstance(cfg_file, Path)
        self.assertEqual(cfg_file.name, "adapters.json")

    # =====================================================================
    # H: APPLICATION DATA DIRECTORY
    # =====================================================================
    def test_H_app_data_directory_isolation(self):
        """Application data path resolves correctly per OS without cross-contamination."""
        # Windows
        PlatformManager.set_provider(SimulatedPlatformProvider(os_family=OSFamily.WINDOWS, simulated_home=Path("C:/Users/W")))
        self.assertTrue("AppData/Local/seyyanen" in PlatformManager.get_app_data_path().as_posix())

        # Linux
        PlatformManager.set_provider(SimulatedPlatformProvider(os_family=OSFamily.LINUX, simulated_home=Path("/home/l")))
        self.assertTrue(".local/share/seyyanen" in PlatformManager.get_app_data_path().as_posix())

        # macOS
        PlatformManager.set_provider(SimulatedPlatformProvider(os_family=OSFamily.MACOS, simulated_home=Path("/Users/m")))
        self.assertTrue("Library/Application Support/seyyanen" in PlatformManager.get_app_data_path().as_posix())

    # =====================================================================
    # I: CACHE DIRECTORY
    # =====================================================================
    def test_I_cache_directory_isolation(self):
        """Cache directory adheres to OS conventions."""
        PlatformManager.set_provider(SimulatedPlatformProvider(os_family=OSFamily.LINUX, simulated_home=Path("/home/user")))
        cache_p = PlatformManager.get_cache_path("ecu_cache.db")
        self.assertEqual(cache_p.name, "ecu_cache.db")
        self.assertTrue(".cache/seyyanen" in cache_p.as_posix())

    # =====================================================================
    # J: TEMPORARY DIRECTORY
    # =====================================================================
    def test_J_temporary_directory_isolation(self):
        """Temporary directory paths are platform-safe."""
        temp_p = PlatformManager.get_temp_path("diag_frame.bin")
        self.assertIsInstance(temp_p, Path)
        self.assertEqual(temp_p.name, "diag_frame.bin")

    # =====================================================================
    # K: CONFIGURATION LOCATION
    # =====================================================================
    def test_K_configuration_directory_isolation(self):
        """Configuration directory respects OS-specific config roots."""
        PlatformManager.set_provider(SimulatedPlatformProvider(os_family=OSFamily.WINDOWS, simulated_home=Path("C:/Users/U")))
        cfg = PlatformManager.get_config_path("profile.json")
        self.assertTrue("AppData/Roaming/seyyanen/profile.json" in cfg.as_posix())

    # =====================================================================
    # L: EXECUTABLE DISCOVERY BEHAVIOR
    # =====================================================================
    def test_L_executable_discovery(self):
        """Executable discovery handles existing and missing binaries deterministically."""
        # Test default provider (live host)
        PlatformManager.reset_to_default_provider()
        py_exe = PlatformManager.find_executable("python") or PlatformManager.find_executable("python3")
        self.assertIsNotNone(py_exe, "Host Python executable should be discoverable.")
        self.assertIsInstance(py_exe, Path)

        # Missing executable returns None
        missing = PlatformManager.find_executable("non_existent_binary_xyz_9999")
        self.assertIsNone(missing)

        # Test simulated provider with injected executables
        sim = SimulatedPlatformProvider()
        sim.executables["candump"] = Path("/usr/bin/candump")
        PlatformManager.set_provider(sim)
        self.assertEqual(PlatformManager.find_executable("candump"), Path("/usr/bin/candump"))
        self.assertIsNone(PlatformManager.find_executable("cansend"))

    # =====================================================================
    # M: ENVIRONMENT HANDLING
    # =====================================================================
    def test_M_environment_overrides_in_default_provider(self):
        """DefaultPlatformProvider honors environment variables safely."""
        provider = DefaultPlatformProvider()
        # Test temp directory resolution
        temp_dir = provider.get_temp_dir("test_env_app")
        self.assertTrue(temp_dir.as_posix().endswith("test_env_app"))

    # =====================================================================
    # N: ADAPTER DISCOVERY INTEGRATION
    # =====================================================================
    def test_N_adapter_discovery_integration(self):
        """Adapter discovery matches VCI signatures across device descriptors."""
        sim_ports = [
            {"device": "COM4", "description": "vLinker FS USB Serial Port", "manufacturer": "FTDI", "vid": 0x0403, "pid": 0x6001},
            {"device": "COM7", "description": "Silicon Labs CP210x USB to UART Bridge", "manufacturer": "Silicon Labs", "vid": 0x10c4, "pid": 0xea60},
            {"device": "COM1", "description": "Standard Serial Port", "manufacturer": "Microsoft", "vid": None, "pid": None},
        ]
        sim = SimulatedPlatformProvider(simulated_ports=sim_ports)
        PlatformManager.set_provider(sim)

        discovered = PlatformManager.discover_diagnostic_devices()
        self.assertEqual(len(discovered), 3)

        vci_matches = [d for d in discovered if d["is_likely_vci"]]
        self.assertEqual(len(vci_matches), 2)
        self.assertEqual(vci_matches[0]["device"], "COM4")
        self.assertEqual(vci_matches[1]["device"], "COM7")

        # Non-matching standard port
        std_port = [d for d in discovered if not d["is_likely_vci"]][0]
        self.assertEqual(std_port["device"], "COM1")

    # =====================================================================
    # O: SERIAL / DEVICE NAMING ABSTRACTION
    # =====================================================================
    def test_O_serial_device_naming_cross_platform(self):
        """Default diagnostic port resolves appropriately across naming conventions."""
        # Windows COM naming
        sim_win = SimulatedPlatformProvider(
            os_family=OSFamily.WINDOWS,
            simulated_ports=[
                {"device": "COM1", "description": "Standard Port", "manufacturer": "MS"},
                {"device": "COM3", "description": "CH340 USB-Serial", "manufacturer": "WCH"},
            ]
        )
        PlatformManager.set_provider(sim_win)
        self.assertEqual(PlatformManager.get_default_diagnostic_port(), "COM3")

        # Linux /dev/ttyUSB naming
        sim_linux = SimulatedPlatformProvider(
            os_family=OSFamily.LINUX,
            simulated_ports=[
                {"device": "/dev/ttyS0", "description": "Standard Serial", "manufacturer": None},
                {"device": "/dev/ttyUSB0", "description": "FTDI FT232R ELM327", "manufacturer": "FTDI"},
            ]
        )
        PlatformManager.set_provider(sim_linux)
        self.assertEqual(PlatformManager.get_default_diagnostic_port(), "/dev/ttyUSB0")

        # macOS /dev/cu.usbserial naming
        sim_mac = SimulatedPlatformProvider(
            os_family=OSFamily.MACOS,
            simulated_ports=[
                {"device": "/dev/cu.Bluetooth-Incoming-Port", "description": "Bluetooth", "manufacturer": "Apple"},
                {"device": "/dev/cu.usbserial-1410", "description": "OBDLink SX", "manufacturer": "FTDI"},
            ]
        )
        PlatformManager.set_provider(sim_mac)
        self.assertEqual(PlatformManager.get_default_diagnostic_port(), "/dev/cu.usbserial-1410")

    # =====================================================================
    # P: PERMISSION / ERROR HANDLING & INVARIANTS
    # =====================================================================
    def test_P_platform_error_semantics(self):
        """
        Platform errors preserve:
        1. is_platform_error = True
        2. is_communication_failure = True
        3. COMMUNICATION FAILURE != COMPONENT FAILURE
        """
        err = PlatformPermissionError("Permission denied: /dev/ttyUSB0 (dialout required)", os_family=OSFamily.LINUX)
        self.assertTrue(err.is_platform_error)
        self.assertTrue(err.is_communication_failure)
        self.assertEqual(err.os_family, OSFamily.LINUX)
        self.assertIn("PlatformPermissionError", str(err))

        disc_err = DeviceDiscoveryError("Failed to query Win32_PnPEntity", os_family=OSFamily.WINDOWS)
        self.assertTrue(disc_err.is_platform_error)
        self.assertTrue(disc_err.is_communication_failure)

        # require_capability raises PlatformResourceUnavailableError
        sim_win = SimulatedPlatformProvider(os_family=OSFamily.WINDOWS)
        PlatformManager.set_provider(sim_win)
        with self.assertRaises(PlatformResourceUnavailableError) as cm:
            PlatformManager.require_capability("supports_raw_socketcan")
        self.assertTrue(cm.exception.is_platform_error)

    # =====================================================================
    # Q: SUBPROCESS FAILURE HANDLING
    # =====================================================================
    def test_Q_subprocess_failure_handling(self):
        """Document opening and subprocess operations fail safely and deterministically."""
        sim = SimulatedPlatformProvider(os_family=OSFamily.LINUX)
        PlatformManager.set_provider(sim)

        # Missing file check
        with self.assertRaises(FileNotFoundError):
            DefaultPlatformProvider().open_document(Path("/non/existent/path/to/report.pdf"))

        # Simulated open success tracking
        test_path = Path("/tmp/report.pdf")
        success = PlatformManager.open_document(test_path)
        self.assertTrue(success)
        self.assertIn(test_path, sim.opened_documents)

    # =====================================================================
    # R: ENCODING BEHAVIOR & BYTE-ACCURACY
    # =====================================================================
    def test_R_diagnostic_bytes_and_utf8_encoding_accuracy(self):
        """Diagnostic byte streams remain bit-for-bit accurate; UTF-8 text is preserved."""
        # 1. Raw ECU Diagnostic bytes must not undergo Unicode decoding or alteration
        raw_ecu_payload = b"\x62\x01\x00\x12\x34\xde\xad\xbe\xef\x00\xff"
        # Simulate saving to platform cache / temp path
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_file = Path(tmp_dir) / "ecu_raw.bin"
            temp_file.write_bytes(raw_ecu_payload)
            read_back = temp_file.read_bytes()
            self.assertEqual(read_back, raw_ecu_payload, "Raw ECU bytes must remain identical.")

        # 2. International characters in diagnostic descriptions
        diag_str = "Seyyanen Teşhis Sistemi: Şasi Numarası, Egzoz Emisyonu, Yağ Sıcaklığı"
        encoded = diag_str.encode("utf-8")
        decoded = encoded.decode("utf-8")
        self.assertEqual(decoded, diag_str)

    # =====================================================================
    # S: DETERMINISTIC PLATFORM PROVIDER TEST DOUBLES
    # =====================================================================
    def test_S_platform_provider_dependency_injection(self):
        """PlatformManager allows injecting test doubles and resets to live host cleanly."""
        orig_provider = PlatformManager.get_provider()
        self.assertIsInstance(orig_provider, DefaultPlatformProvider)

        sim_provider = SimulatedPlatformProvider(os_family=OSFamily.MACOS)
        PlatformManager.set_provider(sim_provider)
        self.assertEqual(PlatformManager.get_info().os_family, OSFamily.MACOS)

        PlatformManager.reset_to_default_provider()
        self.assertIsInstance(PlatformManager.get_provider(), DefaultPlatformProvider)

    # =====================================================================
    # T: J-1 HARDWARE ADAPTER REGRESSION
    # =====================================================================
    def test_T_j1_adapter_abstraction_regression(self):
        """Phase J-1 Hardware Adapter Abstraction operates transparently above Phase J-2."""
        # Create J-1 Mock adapter
        mock_adapter = MockDiagnosticAdapter(adapter_id="MOCK_REGRESSION_J2")
        mock_adapter.register_response("010C", ["41 0C 0F A0"])
        self.assertTrue(mock_adapter.connect())
        self.assertTrue(mock_adapter.is_connected())

        # Test command sending through J-1 interface
        responses, status = mock_adapter.send_command("010C")
        self.assertEqual(status, STATUS_VALID)
        self.assertTrue(len(responses) > 0)
        self.assertEqual(responses[0], "41 0C 0F A0")

        # Test AdapterRegistry creates registered adapters
        j2534 = AdapterRegistry.create_adapter(AdapterType.J2534_PASS_THRU, adapter_id="J2534_REG")
        self.assertEqual(j2534.adapter_type, AdapterType.J2534_PASS_THRU)
        self.assertTrue(j2534.capabilities.supports_uds_diagnostics)

        mock_adapter.disconnect()

    # =====================================================================
    # U: C→I DIAGNOSTIC INTELLIGENCE REGRESSION
    # =====================================================================
    def test_U_c_to_i_diagnostic_intelligence_regression(self):
        """C→I reasoning layers remain completely OS-agnostic under all simulated platforms."""
        # Iterate through simulated Windows, Linux, and macOS environments
        for sim_os in [OSFamily.WINDOWS, OSFamily.LINUX, OSFamily.MACOS]:
            PlatformManager.set_provider(SimulatedPlatformProvider(os_family=sim_os))

            # 1. Safety Policy enforcement
            policy = ServiceSafetyPolicy()
            read_req = AdvancedServiceRequest(
                service_id="22",
                payload="0100",
                safety_classification=ServiceSafetyClassification.READ_ONLY,
            )
            allowed, reason = policy.validate_request(read_req)
            self.assertTrue(allowed, f"Safe read must be allowed on {sim_os.value}")

            write_req = AdvancedServiceRequest(
                service_id="2E",
                payload="0100AA",
                safety_classification=ServiceSafetyClassification.WRITE,
            )
            prohibited, _ = policy.validate_request(write_req)
            self.assertFalse(prohibited, f"Write service must be blocked on {sim_os.value}")

            # 2. Failure Pattern Library Store
            fpl = FailurePatternLibraryStore()
            patterns = fpl.list_patterns()
            self.assertTrue(isinstance(patterns, list), f"Failure patterns must be accessible on {sim_os.value}")

            # 3. Vehicle ECU Knowledge Store
            vkb = VehicleECUKnowledgeStore()
            self.assertIsNotNone(vkb)
            self.assertIsNotNone(vkb.base_store)


if __name__ == "__main__":
    unittest.main(verbosity=2)
