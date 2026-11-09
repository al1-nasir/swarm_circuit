"""Generate local credentials without printing them or replacing an existing .env."""

import argparse
import os
import secrets
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument(
    "--mock", action="store_true", help="Create separate, opt-in .env.mock credentials"
)
args = parser.parse_args()
target = Path(".env.mock" if args.mock else ".env")
text = (
    (f"SWARM_MOCK_BROKER_ENABLED=true\nSWARM_MOCK_BROKER_TOKEN={secrets.token_urlsafe(32)}\n")
    if args.mock
    else (
        "SWARM_DB_PATH=./data/swarmcircuit.db\n"
        "SWARM_PROJECT_ID=11111111-1111-4111-8111-111111111111\n"
        f"SWARM_SDK_PROJECT_TOKEN={secrets.token_urlsafe(32)}\n"
        f"SWARM_OPERATOR_TOKEN={secrets.token_urlsafe(32)}\n"
    )
)
try:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print(f"{target} already exists; preserved existing credentials.")
else:
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    print(f"Created {target} (mode 0600). Keep it local.")
