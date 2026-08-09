try:
    from motor import AutoExpertEngine, MOCK_AVAILABLE
    print(f"✅ Motor module imported successfully.")
    print(f"🔌 Mock Available: {MOCK_AVAILABLE}")
    print("Test passed.")
except Exception as e:
    print(f"❌ Import failed: {e}")
