# PMU Smart Analyzer

Application web locale d'analyse intelligente des courses hippiques PMU. Affiche les courses du jour, calcule un score pour chaque cheval, et identifie les value bets.

## Prérequis

- Python 3.11+
- Connexion internet (pour récupérer les données PMU)

## Installation

```bash
cd PMU-Smart-Analyzer
pip install -r requirements.txt
```

## Lancement

```bash
python main.py
```

Puis ouvrir **http://localhost:8000** dans le navigateur.

> Sur mobile : connectez votre téléphone au même réseau Wi-Fi et accédez à `http://<IP-de-votre-PC>:8000`

## Fonctionnalités

### Dashboard
- Résumé du jour : nombre de réunions, courses, value bets détectés
- Top 5 picks toutes courses confondues
- Liste des réunions avec accès rapide aux courses

### Courses
- Liste complète des courses du jour groupées par hippodrome
- Détails : heure, distance, discipline, terrain, prize money, nombre de partants

### Analyse par course
- Tous les partants triés par score décroissant (0-100)
- Top Pick mis en avant avec justification
- Value Bets signalés en vert avec explication
- Tap sur un cheval → détail complet du score par critère
- Affichage de la musique (historique des performances)

## Moteur de scoring

Le score (0-100) est calculé sur 6 critères :

| Critère | Poids | Description |
|---|---|---|
| Forme récente | 35% | Analyse de la musique (5 dernières courses pondérées) |
| Cote / Valeur | 25% | Rapport entre cote et probabilité estimée |
| Jockey | 15% | Score basé sur le jockey |
| Entraîneur | 10% | Score basé sur l'entraîneur |
| Distance | 8% | Adéquation avec la distance préférée |
| Terrain | 7% | Adéquation avec le pénétromètre |

**Value Bet** = cheval dont la cote réelle est ≥ 30% supérieure à sa probabilité estimée **ET** score ≥ 50.

## Structure du projet

```
PMU-Smart-Analyzer/
├── main.py              # Serveur FastAPI (point d'entrée)
├── requirements.txt
├── app/
│   ├── config.py        # Configuration et constantes
│   ├── database.py      # SQLite async
│   ├── models.py        # Modèles ORM
│   ├── schemas.py       # Schémas Pydantic
│   ├── pmu_client.py    # Client API PMU turfinfo
│   ├── scoring.py       # Moteur de scoring
│   ├── service.py       # Logique de chargement des données
│   └── routers/
│       ├── courses.py   # Endpoints /api/courses
│       └── dashboard.py # Endpoint /api/dashboard
└── static/
    ├── index.html       # SPA mobile-first
    ├── css/style.css
    └── js/
        ├── api.js       # Fetch helpers
        ├── components.js # Composants UI
        └── app.js       # Logique principale
```

## API REST

| Endpoint | Description |
|---|---|
| `GET /api/dashboard` | Résumé du jour + top picks |
| `GET /api/reunions` | Liste des réunions avec courses |
| `GET /api/courses` | Liste des courses |
| `GET /api/courses/{id}` | Détail + participants + scores |
| `POST /api/refresh` | Rechargement depuis l'API PMU |

Documentation interactive : http://localhost:8000/docs

## Notes

- Les données sont récupérées depuis l'API publique PMU (`turfinfo.api.pmu.fr`)
- Le programme du jour est chargé au premier démarrage et mis en cache dans SQLite
- Les participants sont chargés à la demande (au premier accès à une course)
- Utilisez le bouton ↺ pour forcer le rechargement
