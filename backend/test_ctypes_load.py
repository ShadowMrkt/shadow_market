# File: test_ctypes_load.py
import ctypes
import ctypes.util
import os
import platform

print(f"Python Arch: {platform.architecture()}")
print(f"PATH: {os.environ.get('PATH')}")

# Add known OpenSSL paths if needed (replace with your actual paths)
#if platform.system() == "Windows":
#    try:
#        os.add_dll_directory(r"C:\Program Files\OpenSSL-Win64\bin") # For OpenSSL 3.x
#        os.add_dll_directory(r"C:\Program Files\OpenSSL\bin")      # For OpenSSL 1.1.1 if installed there
#        print("Attempted to add OpenSSL dirs to DLL search path.")
#    except Exception as e:
#        print(f"Error adding DLL directory: {e}")

# Try common names ctypes might look for on Windows
lib_names = ['libcrypto-3-x64', 'libssl-3-x64', 'libcrypto-1_1-x64', 'libssl-1_1-x64', 'libcrypto', 'libssl', 'libeay32', 'ssleay32']
found_path = None
print("\n--- Checking find_library ---")
for name in lib_names:
    try:
        path = ctypes.util.find_library(name)
        if path:
            print(f"ctypes.util.find_library found '{name}' at: {path}")
            if not found_path and name in ['libcrypto', 'libeay32', 'ssl']: # Prioritize names bitcoinlib might use
                 found_path = path
        else:
            print(f"ctypes.util.find_library did NOT find '{name}'")
    except Exception as e:
        print(f"Error calling find_library for '{name}': {e}")

if found_path:
    print(f"\nAttempting to load best found library: {found_path}")
    try:
        loaded_lib = ctypes.cdll.LoadLibrary(found_path)
        print(f"Successfully loaded library: {loaded_lib}")
    except Exception as e:
        print(f"FAILED to load library {found_path}: {e}")
        import traceback
        traceback.print_exc()
else:
    print("\nCould not find any preferred OpenSSL library names via ctypes.util.find_library.")
    # Try loading OpenSSL 1.1.1 directly if find_library fails
    known_path_111 = r"C:\Program Files\OpenSSL\bin\libcrypto-1_1-x64.dll" # Adjust if your 1.1.1 path/name is different (e.g., libeay32.dll)
    print(f"\nAttempting direct load of OpenSSL 1.1.1: {known_path_111}")
    try:
         loaded_lib = ctypes.cdll.LoadLibrary(known_path_111)
         print(f"Successfully loaded library directly: {loaded_lib}")
    except Exception as e:
         print(f"FAILED to load library {known_path_111} directly: {e}")
         # import traceback
         # traceback.print_exc() # Usually just FileNotFoundError if path is wrong