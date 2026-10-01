"""
Launcher for the EPANET 2.2 Local AI & Engineering Analytics Service.

Usage (from repository root):
    python -m ai_module.run_service                 # default 127.0.0.1:8765
    python -m ai_module.run_service --port 9000

Windows convenience:
    start_ai_service.bat
"""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="EPANET 2.2 Local AI Service launcher")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")
    args = parser.parse_args()

    import uvicorn

    print("=" * 72)
    print("  EPANET 2.2 Local AI & Engineering Analytics Service")
    print("  Delphi UI button 'AI' -> POST http://127.0.0.1:8765/api/v1/analyze")
    print("=" * 72)
    print(f"  Host:  http://{args.host}:{args.port}")
    print(f"  Docs:  http://{args.host}:{args.port}/docs")
    print(f"  Health: http://{args.host}:{args.port}/api/v1/health")
    print("=" * 72)

    uvicorn.run("ai_module.api.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
