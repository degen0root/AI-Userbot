#!/usr/bin/env python3
"""
Test runner for AI UserBot
"""

import subprocess
import sys
from pathlib import Path

def run_tests():
    """Run all tests"""
    tests_dir = Path(__file__).parent / "tests"

    if not tests_dir.exists():
        print("❌ Tests directory not found!")
        return 1

    # Install test requirements if needed
    test_requirements = tests_dir / "requirements.txt"
    if test_requirements.exists():
        print("📦 Installing test dependencies...")
        subprocess.run([
            sys.executable, "-m", "pip", "install", "-r", str(test_requirements)
        ], check=True)

    # Run tests
    print("🧪 Running tests...")
    result = subprocess.run([
        sys.executable, "-m", "pytest", str(tests_dir), "-v"
    ], cwd=Path(__file__).parent)

    return result.returncode

if __name__ == "__main__":
    sys.exit(run_tests())
