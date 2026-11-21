# Host-side OBD parser tests

These tests compile the same portable parser source used by the firmware. They
do not access a COM port, Bluetooth adapter, ECU, or display.

From the repository root, with a desktop C++11 compiler installed:

```powershell
$testExe = Join-Path $env:TEMP 'obd_response_parser_test.exe'
g++ -std=c++11 -Wall -Wextra -pedantic `
  -I mini_seyyanen_esp32/src `
  mini_seyyanen_esp32/src/obd_response_parser.cpp `
  mini_seyyanen_esp32/test_host/obd_response_parser_test.cpp `
  -o $testExe
& $testExe
```

Coverage includes command echoes, spaced and headered responses, adapter status
text, incomplete/wrong PID replies, mixed positive and negative ECU replies,
multiple ECUs, the `0100` target bitmap, and the five conversion formulas.
The VLinker connection and OBD state machine still require physical or mocked
transport integration tests.
