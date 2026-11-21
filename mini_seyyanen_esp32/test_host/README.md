# Host-side OBD parser and state-machine tests

The parser test compiles the same parser source used by the firmware. The
state-machine test compiles the real `VlinkerClient` and `ObdManager` against a
small fake Bluetooth transport and Arduino/FreeRTOS compatibility stubs. Tests
do not access a COM port, Bluetooth adapter, ECU, or display.

From the repository root, in a Visual Studio Developer PowerShell (C++11
language features; MSVC `/std:c++14`):

```powershell
$project = (Resolve-Path 'mini_seyyanen_esp32').Path
$outDir = Join-Path $env:TEMP 'seyyanen_host_tests'
New-Item -ItemType Directory -Force $outDir | Out-Null
$parserExe = Join-Path $outDir 'obd_response_parser_test.exe'
$stateExe = Join-Path $outDir 'obd_state_machine_test.exe'
Push-Location $outDir
try {
  cl /nologo /EHsc /std:c++14 /I"$project\src" `
    "$project\src\obd_response_parser.cpp" `
    "$project\test_host\obd_response_parser_test.cpp" /Fe:"$parserExe"
  if ($LASTEXITCODE -ne 0) { throw 'Parser test build failed' }
  & $parserExe
  if ($LASTEXITCODE -ne 0) { throw 'Parser tests failed' }

  cl /nologo /EHsc /std:c++14 /I"$project\test_host\support" `
    /I"$project\include" /I"$project\src" `
    "$project\src\obd_response_parser.cpp" `
    "$project\src\vlinker_client.cpp" `
    "$project\src\obd_manager.cpp" `
    "$project\test_host\obd_state_machine_test.cpp" /Fe:"$stateExe"
  if ($LASTEXITCODE -ne 0) { throw 'State-machine test build failed' }
  & $stateExe
  if ($LASTEXITCODE -ne 0) { throw 'State-machine tests failed' }
}
finally { Pop-Location }
```

Parser coverage includes echoes, spaced/headered/headerless frames, mixed
positive/negative replies, malformed lengths, oversized lines, frame capacity,
multiple ECUs, and the five conversions. State-machine coverage uses a fake SPP
transport for initialization, AUTO/KWP discovery, PID polling/failures, stale
data, late prompts/resynchronization, reconnect, and ECU ambiguity. Simulations
do not establish physical VLinker MC+ or Aveo ECU compatibility.
