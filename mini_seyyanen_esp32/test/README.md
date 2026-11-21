# Verification notes

Run the portable parser tests in `../test_host/` with a desktop C++11 compiler. They do not exercise the OBD state machine or Bluetooth transport.

Run the staged hardware checks in the project README with the actual ESP32-2432S028R, VLinker MC+, and vehicle. The repository has no hardware-in-the-loop test harness for the live Bluetooth/ECU state machine.
