#!/usr/bin/env python3
"""
MomoTalk IRL — Bot Launcher
Usage:
    python run.py hina        # Run just Hina
    python run.py arona       # Run just Arona
    python run.py all         # Run all bots (not recommended for development)
"""
import sys
import subprocess
import os
from config import get_token

CHARACTERS = {
    "hina": "characters/hina.py",
    "arona": "characters/arona.py",
    "rio": "characters/rio.py",
    "plana": "characters/plana.py",
    "hoshino": "characters/hoshino.py",
    "ako": "characters/ako.py",
    "yuuka": "characters/yuuka.py",
    "aru": "characters/aru.py",
    "mutsuki": "characters/mutsuki.py",
    "kayoko": "characters/kayoko.py",
    "alice": "characters/alice.py",
    "momoi": "characters/momoi.py",
    "midori": "characters/midori.py",
    "hanako": "characters/hanako.py",
    "shioko": "characters/shioko.py",
    "reisa": "characters/reisa.py",
    "ui": "characters/ui.py",
    "yuzu": "characters/yuzu.py",
}


def main():
    if len(sys.argv) < 2:
        print("Usage: python run.py <character|all>")
        print(f"Available: {', '.join(CHARACTERS.keys())}, all")
        sys.exit(1)

    target = sys.argv[1].lower()
    base_dir = os.path.dirname(os.path.abspath(__file__))

    if target == "all":
        # Launch all bots as separate processes
        processes = []
        for name, script in CHARACTERS.items():
            # Check if token exists
            try:
                get_token(name)
                print(f"Starting {name}...")
                p = subprocess.Popen(
                    [sys.executable, os.path.join(base_dir, script)],
                    cwd=base_dir,
                )
                processes.append((name, p))
            except ValueError:
                print(f"Skipping {name} (no token configured)")

        print(f"\nAll {len(processes)} bots launched.")
        print("Press Ctrl+C to stop all.\n")

        try:
            for name, p in processes:
                p.wait()
        except KeyboardInterrupt:
            print("\nStopping all bots...")
            for name, p in processes:
                p.terminate()
                print(f"  Stopped {name}")

    elif target in CHARACTERS:
        script = os.path.join(base_dir, CHARACTERS[target])
        print(f"Starting {target}...")
        subprocess.run([sys.executable, script], cwd=base_dir)

    else:
        print(f"Unknown character: {target}")
        print(f"Available: {', '.join(CHARACTERS.keys())}, all")
        sys.exit(1)


if __name__ == "__main__":
    main()
