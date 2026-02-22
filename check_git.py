import subprocess
import os

def run_command(cmd):
    print(f"\n--- Running: {' '.join(cmd)} ---")
    try:
        # On Windows, we might need shell=True if git is not in PATH or similar issues
        # But subprocess usually handles PATH fine.
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error (code {result.returncode}):")
            print(result.stderr)
        else:
            print(result.stdout)
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    run_command(["git", "--no-pager", "log", "-1"])
    run_command(["git", "--no-pager", "show", "--stat", "HEAD"])
    run_command(["git", "status"])
