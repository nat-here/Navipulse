"""Initialize the persistent synthetic dataset without launching Reflex."""
from disruption_iq.engine import init_db,DB_PATH
init_db()
print("Ready:",DB_PATH)
