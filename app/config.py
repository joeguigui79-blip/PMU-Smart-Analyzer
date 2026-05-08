import os
from datetime import datetime
from zoneinfo import ZoneInfo

PMU_BASE_URL = "https://offline.turfinfo.api.pmu.fr/rest/client/7/programme"
PMU_PARTICIPANTS_URL = "https://offline.turfinfo.api.pmu.fr/rest/client/7/programme/{date}/R{reunion}/C{course}/participants"
PMU_ARRIVEE_URL = "https://offline.turfinfo.api.pmu.fr/rest/client/7/programme/{date}/R{reunion}/C{course}/arrivee"

# DATABASE_URL format attendu: postgresql+asyncpg://user:password@host:port/dbname
# Supabase fournit une URL postgres:// ou postgresql:// — conversion automatique ci-dessous.
# Sans DATABASE_URL dans l'environnement, fallback SQLite local.
_raw_db_url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./pmu_analyzer.db")
if _raw_db_url.startswith("postgres://"):
    DATABASE_URL = _raw_db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif _raw_db_url.startswith("postgresql://"):
    DATABASE_URL = _raw_db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = _raw_db_url

PARIS_TZ = ZoneInfo("Europe/Paris")

def today_str() -> str:
    """Date du jour au format DDMMYYYY pour l'API PMU."""
    return datetime.now(PARIS_TZ).strftime("%d%m%Y")

# Pondérations différenciées par discipline (somme = 1.0 pour chaque)
SCORING_WEIGHTS_DISCIPLINE = {
    "PLAT": {
        "forme_recente": 0.32,
        "value_cote":    0.15,
        "jockey":        0.12,
        "entraineur":    0.08,
        "distance":      0.10,
        "terrain":       0.08,
        "repos":         0.05,
        "gains":         0.05,
        "age":           0.03,
        "partants":      0.02,
        "hippodrome":    0.00,
    },
    "TROT_ATTELE": {
        "forme_recente": 0.26,
        "value_cote":    0.14,
        "corde":         0.16,
        "regularite":    0.13,
        "gains":         0.07,
        "recence":       0.08,
        "entraineur":    0.06,
        "distance":      0.05,
        "age":           0.03,
        "partants":      0.02,
    },
    "TROT_MONTE": {
        "forme_recente": 0.27,
        "value_cote":    0.14,
        "corde":         0.13,
        "regularite":    0.11,
        "gains":         0.07,
        "recence":       0.08,
        "jockey":        0.08,
        "entraineur":    0.05,
        "distance":      0.04,
        "age":           0.03,
    },
    "HAIE": {
        "forme_recente": 0.30,
        "value_cote":    0.14,
        "jockey":        0.15,
        "terrain":       0.15,
        "entraineur":    0.08,
        "distance":      0.07,
        "gains":         0.05,
        "age":           0.03,
        "partants":      0.03,
    },
    "STEEPLE": {
        "forme_recente": 0.30,
        "value_cote":    0.14,
        "jockey":        0.15,
        "terrain":       0.15,
        "entraineur":    0.08,
        "distance":      0.07,
        "gains":         0.05,
        "age":           0.03,
        "partants":      0.03,
    },
    "CROSS": {
        "forme_recente": 0.30,
        "value_cote":    0.14,
        "jockey":        0.15,
        "terrain":       0.15,
        "entraineur":    0.08,
        "distance":      0.07,
        "gains":         0.05,
        "age":           0.03,
        "partants":      0.03,
    },
}

# Rétro-compatibilité : référence aux poids PLAT
SCORING_WEIGHTS = SCORING_WEIGHTS_DISCIPLINE['PLAT']

# Seuil value bet : cote réelle >= facteur * probabilité implicite estimée
VALUE_BET_FACTOR = 1.30
VALUE_BET_MIN_SCORE = 50
