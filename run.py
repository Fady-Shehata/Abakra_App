"""Local launcher.

Usage examples:
    python run.py
    python run.py 8001

If port 8000 is busy, pass another port or set ABAKRA_PORT.
"""
import os
import sys

import uvicorn

if __name__ == "__main__":
    cli_port = int(sys.argv[1]) if len(sys.argv) > 1 else None
    port = cli_port or int(os.environ.get("ABAKRA_PORT", "8000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)
