import time
try:
    from motor import AutoExpertEngine
    from mock_serial import MockSerial
    print("Files imported successfully.")
    
    # Simple Mock Test
    mock = MockSerial()
    mock.write(b"AT DP\r")
    time.sleep(0.5)
    resp = mock.read(100)
    print(f"Mock Response to AT DP: {resp}")
    
    if b"KWP" in resp:
        print("✅ Mock Simulates KWP correctly.")
    else:
        print("❌ Mock KWP check failed.")

except Exception as e:
    print(f"❌ Error: {e}")
