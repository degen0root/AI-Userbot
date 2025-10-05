#!/usr/bin/env python3
"""
Convenience script to run the AI UserBot
"""

import sys
from src.ai_userbot.app import main
import asyncio

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
