# SeyyanenBeta

SeyyanenBeta is an automotive diagnostics workspace with a desktop diagnostic application, reusable OBD/ECU analysis modules, and two separate ESP32 acquisition projects. The Python application can work with live adapters and diagnostic/session data; real vehicle behavior depends on the selected adapter, vehicle, and project configuration.

> **Repository status:** This is an initial root README draft. The repository currently has no pinned Python dependency manifest or single automated test command. Historical phase reports describe their own test runs and should not be treated as current hardware verification.

## Main entry points

- `main_ui.py` starts the desktop Qt interface.
- `main.py` runs the console/report workflow.
- `diagnostic_adapter.py` includes the adapter/probe interface and command-line port probe.

To start the desktop UI from the repository root:

```powershell
python main_ui.py
```

To run the console workflow:

```powershell
python main.py
```

The desktop source imports PyQt6, pyqtgraph, NumPy, pandas, matplotlib, pyserial, and an `fpdf.FPDF` provider across its features. Some report functionality is optional. There is currently no `requirements.txt`, `pyproject.toml`, or lock file, so package versions and a reproducible one-command Python installation are not defined. Create an isolated Python environment and resolve the needed packages for the selected entry point before running it; do not assume an unpinned environment is reproducible.

## Repository projects

| Path | Purpose |
| --- | --- |
| `seyyanen_mini/` | Standalone PlatformIO ESP32 acquisition companion. Its project README documents Bluetooth Classic SPP, OBD acquisition, a local Web UI, and SD session storage. |
| `mini_seyyanen_esp32/` | Separate PlatformIO dashboard project for the ESP32-2432S028R and VLinker MC+. Keep its board assumptions and hardware verification status in its own README. |
| `seyyanen_mini_import/` | Python package for reading and validating Mini session exports for the desktop workflow. |
| `dbCSV/` | OBD, DTC, protocol, and vehicle/ECU reference data. Runtime-generated files do not belong in this catalog. |
| `library/` | Reference manuals and protocol documents. |
| `fonts/` | Fonts used by the report-generation code. |
| `rapor/`, `pdf/` | Generated report output paths. Runtime outputs are ignored; reviewed, sanitized examples should be kept separately if needed. |

The two ESP32 directories are independent PlatformIO projects. Build each from the repository root with:

```powershell
pio run -d seyyanen_mini
pio run -d mini_seyyanen_esp32
```

Upload and serial-monitor details are board-specific and are documented in each project README. For example, `mini_seyyanen_esp32/README.md` covers CH340 port selection and its default display configuration. A successful firmware build does not verify the display, adapter, or vehicle connection.

## Host-side tests

The repository contains unittest suites, manually run phase scripts, virtual transports, and hardware acceptance procedures. They are not all discovered by one test runner. The following isolated host-side commands were run successfully during the repository audit:

```powershell
python -m unittest tests.unit.test_virtual_elm327 -v
python -m tests.integration.test_virtual_elm327_integration
python -m unittest discover -s seyyanen_mini/test -p "test_*.py" -v
python -m unittest tests.unit.test_m8_import -v
```

These tests use virtual/fake transports or host-side fixtures; they do not prove physical adapter or ECU communication. The 59 historical phase suites are opt-in under `tests/phase_archive/` and renamed so default pytest/unittest discovery does not collect them. See `tests/README.md`. Follow the corresponding walkthrough for those suites and check whether a test targets a real COM port or persistent data before running it.

## Hardware verification

Hardware walkthroughs and validation notes are organized under `docs/hardware/`; historical project reports are under `docs/history/`. Project READMEs remain with their projects. Historical “pass” statements are tied to the environment and test date in those documents; they are not a substitute for repeating the test on the current firmware and hardware. In particular, do not infer physical ECU communication from a Bluetooth link, a simulated transport, or a successful compile.

## Data and generated files

Runtime logs, caches, build outputs, generated reports, and vehicle session captures can contain diagnostic or identifying data. Keep them out of public commits unless they have been reviewed and sanitized. `dbCSV/nrc_log.csv` has been moved out of the repository working tree into the ignored local-only area. Earlier Git commits still contain historical versions; removing them from Git history is a separate history-rewrite operation.
