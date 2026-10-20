import subprocess, sys, os

req_file = os.path.join(os.path.dirname(__file__), "requirements.txt")
try:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", req_file],
        capture_output=True, text=True, timeout=120,
    )
    # Write output to log
    with open(os.path.join(os.path.dirname(__file__), "install.log"), "w") as f:
        f.write(result.stdout + "\n" + result.stderr)
except Exception as e:
    with open(os.path.join(os.path.dirname(__file__), "install.log"), "w") as f:
        f.write(f"Install failed: {e}")
