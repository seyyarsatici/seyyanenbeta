import importlib.util
import os

_spec = importlib.util.spec_from_file_location("mock_serial_impl", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".mock_serial.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
MockSerial = _mod.MockSerial
