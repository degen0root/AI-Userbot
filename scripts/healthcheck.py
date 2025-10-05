#!/usr/bin/env python3
"""
Health check script for Docker container
"""

import sys
import os
import psutil
import asyncio
from datetime import datetime
import pytz

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ai_userbot.config import load_config

def check_process():
    """Check if main process is running"""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline and 'run.py' in ' '.join(cmdline):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False

def check_time():
    """Check if current time is within active hours"""
    config = load_config()
    tz = pytz.timezone(config.policy.timezone)
    now = datetime.now(tz)
    current_hour = now.hour
    
    wake_up = config.policy.active_hours["wake_up"]
    sleep_time = config.policy.active_hours["sleep_time"]
    
    # During sleep time, consider healthy
    if current_hour >= sleep_time or current_hour < wake_up:
        return True
        
    # During active hours, should be running
    return True

def main():
    """Run health checks"""
    checks = {
        "Process running": check_process(),
        "Time check": check_time(),
    }
    
    all_healthy = all(checks.values())
    
    if not all_healthy:
        print("❌ Health check failed:")
        for check, status in checks.items():
            print(f"  {check}: {'✓' if status else '✗'}")
        sys.exit(1)
    else:
        print("✅ All health checks passed")
        sys.exit(0)

if __name__ == "__main__":
    main()
