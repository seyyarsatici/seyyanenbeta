# Test layout and safe discovery

- `unit/` contains the reviewed host-side unittest suites.
- `integration/` contains host-side scripts with explicit `python -m` runners; they do not require a live adapter.
- `phase_archive/` keeps 59 historical, opt-in suites. Their filenames begin with `phase_`, not `test_`, so default pytest and unittest patterns do not collect them. Connection-call candidates include `phase_c2`–`phase_c6`, `phase_d1`–`phase_d3`, `phase_e_final`, `phase_e2`, `phase_e4`, `phase_f1`–`phase_f5`, and `phase_g4`; these contain `baglan()` call sites whose physical behavior depends on simulation/configuration. Review each before explicit execution. `phase_k2_real_com` injects fake port and serial objects, but remains archived.
- `manual/` contains opt-in tools. `reset_manual.py` can choose and open a physical COM port. `active_test.py` contains UDS sessions/security-access and sends an example `31 01 01` routine command. Do not run it against a live vehicle.
- `benchmark/` contains performance workloads.
- The dynamically loaded `.mock_serial.py` remains at repository root because `mock_serial.py` resolves it there.

## Safe default commands

Run from repository root:

```powershell
python -m unittest discover -s tests/unit -t . -v
python -m unittest discover -s tests -t . -v
python -m tests.integration.test_virtual_elm327_integration
python -m tests.integration.test_c_layer_integration
python -m tests.integration.test_d_layer_hardening
python -m unittest discover -s seyyanen_mini/test -p "test_*.py" -v
```

`test_vin_parser.py` is a standalone host parser script with pytest-style functions, not a unittest `TestCase`. If pytest is unavailable, run it explicitly from any directory with `python <repo-root>/tests/unit/test_vin_parser.py`; on Windows set `$env:PYTHONIOENCODING = "utf-8"` first so its Unicode console output is supported. Its import path is derived from `__file__`, not the current directory.

`pytest.ini` limits default pytest discovery to the reviewed unit/integration directories and `seyyanen_mini/test`; `manual/` and `phase_archive/` are excluded. The archive remains opt-in even when a caller supplies a custom test path because its filenames do not match the default test patterns.

Explicit examples (review requirements before running):

```powershell
python -m unittest tests.phase_archive.phase_j_final -v
python -m tests.phase_archive.phase_f7
python -m tests.manual.reset_manual
python -m tests.manual.active_test
```

The F7 runner currently verifies the adapter reconnect path with mocks. The reset and active-test commands can touch real diagnostics; do not run them on a live vehicle.

## Fixture privacy

`seyyanen_mini/MINI_REAL_VEHICLE_VALIDATION_SESSION/session.csv` remains the canonical M8 import fixture. Its directory and historical documents label it as a real-vehicle validation session. I cannot establish that its sensor measurements are synthetic; treat publication as pending privacy review.
