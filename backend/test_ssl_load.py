print("Attempting to import bitcoin.core.key...")
try:
    import bitcoin.core.key
    print("Import successful!")
    # You could potentially add a line here that uses the key module slightly
    # key = bitcoin.core.key.CKey.generate()
    # print("Key generation attempted.")
except Exception as e:
    print(f"Import failed: {e}")
    import traceback
    traceback.print_exc()