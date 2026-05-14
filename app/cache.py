"""
Module de cache en mémoire simple avec TTL (Time To Live).

Réduit les requêtes vers Neon PostgreSQL en mettant en cache les résultats
des endpoints coûteux en lecture.

Usage:
    from app.cache import cache

    # Lire depuis le cache
    data = cache.get("ma_cle")

    # Écrire dans le cache avec TTL (secondes)
    cache.set("ma_cle", data, ttl=300)

    # Invalider une entrée
    cache.delete("ma_cle")

    # Vider tout le cache
    cache.clear()

    # Vider les entrées expirées
    cache.evict_expired()
"""

import time
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MemoryCache:
    """Cache en mémoire thread-safe (asyncio) avec TTL par entrée."""

    def __init__(self):
        # { key: (value, expires_at) }
        self._store: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        """Retourne la valeur associée à la clé si elle existe et n'est pas expirée."""
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """Stocke une valeur avec un TTL en secondes."""
        self._store[key] = (value, time.monotonic() + ttl)

    def delete(self, key: str) -> bool:
        """Supprime une entrée. Retourne True si elle existait."""
        return self._store.pop(key, None) is not None

    def delete_prefix(self, prefix: str) -> int:
        """Supprime toutes les entrées dont la clé commence par le préfixe. Retourne le nombre supprimé."""
        keys_to_delete = [k for k in self._store if k.startswith(prefix)]
        for k in keys_to_delete:
            del self._store[k]
        return len(keys_to_delete)

    def clear(self) -> int:
        """Vide l'intégralité du cache. Retourne le nombre d'entrées supprimées."""
        count = len(self._store)
        self._store.clear()
        logger.info("Cache entièrement vidé (%d entrées supprimées)", count)
        return count

    def evict_expired(self) -> int:
        """Supprime les entrées expirées. Retourne le nombre d'entrées supprimées."""
        now = time.monotonic()
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
        if expired:
            logger.debug("Cache: %d entrées expirées supprimées", len(expired))
        return len(expired)

    def stats(self) -> dict:
        """Retourne des statistiques sur le cache."""
        now = time.monotonic()
        total = len(self._store)
        expired = sum(1 for _, (_, exp) in self._store.items() if now > exp)
        return {
            "total_entries": total,
            "active_entries": total - expired,
            "expired_entries": expired,
        }


# Instance globale unique partagée par tous les modules
cache = MemoryCache()

# TTL par endpoint (en secondes)
TTL_DASHBOARD = 300      # 5 minutes
TTL_PRONOSTICS = 300     # 5 minutes
TTL_BILAN = 600          # 10 minutes
TTL_STATS = 600          # 10 minutes
TTL_COURSES_DU_JOUR = 300  # 5 minutes
TTL_REUNIONS = 300       # 5 minutes
