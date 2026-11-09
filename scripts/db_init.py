from pathlib import Path

from dotenv import load_dotenv
from swarmcircuit_server.config import Settings
from swarmcircuit_server.db.store import connect, migrate
from swarmcircuit_server.repository import bootstrap

load_dotenv(Path(".env"))
settings = Settings.from_env()
migrate(settings.db_path)
conn = connect(settings.db_path)
try:
    with conn:
        bootstrap(conn, settings)
finally:
    conn.close()
print("Schema 004 ready.")
