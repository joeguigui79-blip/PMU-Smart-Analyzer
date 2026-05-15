# Analyse PMU Smart Analyzer — 12/05/2026

## Périmètre et méthode

Analyse réalisée sans modification du code, à partir de :

- l’API Render protégée (`/api/login`, `/api/bilan`, `/api/scoring/accuracy-by-discipline`, `/api/scoring/discipline-stats`, `/api/stats/scoring`, `/api/stats/calibration`)
- la base locale `pmu_analyzer.db`
- la lecture du moteur de scoring dans `app/scoring.py`, des poids dans `app/config.py`, et de la calibration dans `app/calibration.py`

## Important — qualité et limites des données

Deux niveaux de données coexistent :

1. **Vue production Render**  
   Donne des agrégats robustes par discipline et par mode sur **264 courses terminées**.

2. **Vue locale détaillée depuis le 08/05/2026**  
   Donne les détails participants/résultats sur **41 courses** et **391 partants** entre **08/05/2026** et **11/05/2026**.

En conséquence :

- les **recommandations par logique/poids** s’appuient d’abord sur la **vue Render** pour éviter les conclusions fragiles
- les **seuils value bet** et certains patterns récents s’appuient sur la **fenêtre locale 08/05→11/05**
- les conclusions sur **HAIE** et **STEEPLE** restent **faiblement fiables** faute d’échantillon suffisant

---

## 1) Ce que fait actuellement le scoring

### Poids experts configurés

Référentiel lu dans `app/config.py` :

- **PLAT** : forme 0.32, cote 0.15, jockey 0.12, distance 0.10, terrain 0.08, entraîneur 0.08, repos 0.05, gains 0.05, âge 0.03, partants 0.02
- **TROT_ATTELE** : forme 0.26, cote 0.14, corde 0.16, régularité 0.13, récence 0.08, gains 0.07, entraîneur 0.06, distance 0.05, âge 0.03, partants 0.02
- **TROT_MONTE** : forme 0.27, cote 0.14, corde 0.13, régularité 0.11, récence 0.08, jockey 0.08, gains 0.07, entraîneur 0.05, distance 0.04, âge 0.03
- **HAIE/STEEPLE/CROSS** : forme 0.30, cote 0.14, jockey 0.15, terrain 0.15, entraîneur 0.08, distance 0.07, gains 0.05, âge 0.03, partants 0.03

### Règles clés lues dans le code

- `score_global` utilise le **mode auto** si des poids calibrés existent, sinon le **mode expert**
- `score_sans_cote` retire complètement le poids `value_cote`
- le **bonus outsider** est **désactivé en PLAT** et peut ajouter jusqu’à **30 points** hors plat pour les chevaux à grosse cote
- un cheval est **value bet** si :
  - `score_global >= VALUE_BET_MIN_SCORE`
  - et `score_global / 100 >= (1 / cote) * VALUE_BET_FACTOR`
- paramètres actuels :
  - `VALUE_BET_FACTOR = 1.30`
  - `VALUE_BET_MIN_SCORE = 50`

---

## 2) Résultats observés par discipline

## 2.1 Vue Render — robustesse par discipline et par mode

### Taux top-1 exact par mode

| Discipline | Courses | Expert | Auto | Sans cote | Mode recommandé actuel |
|---|---:|---:|---:|---:|---|
| PLAT | 118 | **18.6%** | 16.9% | 17.8% | **expert** |
| TROT_ATTELE | 119 | 14.3% | **20.2%** | 15.1% | **auto** |
| TROT_MONTE | 17 | **23.5%** | 17.6% | **23.5%** | **expert / sans cote** |
| HAIE | 6 | 16.7% | 50.0% | 0.0% | auto* |
| STEEPLE | 4 | 25.0% | 50.0% | 75.0% | sans cote* |

\* échantillon trop faible pour en tirer une règle de production.

### Lecture métier

- **PLAT** : l’auto-calibration actuelle **dégrade** le top-1 par rapport à l’expert.
- **TROT_ATTELE** : l’auto-calibration apporte un gain réel (**+5.9 points** vs expert).
- **TROT_MONTE** : l’auto surpondère trop la cote, et l’expert reste préférable.
- **Obstacle** : les résultats semblent très sensibles à la cote, mais l’échantillon est insuffisant pour changer les poids de façon fiable.

## 2.2 Vue locale détaillée depuis le 08/05/2026

### Performance récente sur 41 courses

| Discipline | Courses | Top1 gagnant | Top1 top3 | Spearman score_global | Value bets | Value bets top3 | ROI gagnant seul |
|---|---:|---:|---:|---:|---:|---:|---:|
| PLAT | 14 | 14.3% | 35.7% | **0.388** | 19 | 42.1% | **-51.1%** |
| TROT_ATTELE | 21 | **33.3%** | **57.1%** | 0.308 | 86 | 44.2% | **+9.4%** |
| TROT_MONTE | 3 | 0.0% | 33.3% | 0.351 | 17 | 41.2% | +78.8%* |
| HAIE | 2 | 0.0% | 50.0% | **-0.221** | 8 | 25.0% | -100.0% |
| STEEPLE | 1 | 100.0%* | 100.0%* | 0.607* | 4 | 50.0% | +27.5%* |

\* échantillon trop faible pour être interprété comme une tendance.

### Conclusion récente

- la fenêtre récente confirme que **le trot attelé est la meilleure discipline actuelle**
- **le plat sous-performe clairement**
- les **value bets en plat détruisent de la valeur**
- les **value bets en trot attelé restent exploitables**, mais sont trop nombreux

---

## 3) Analyse des critères de scoring

## 3.1 Corrélations et précision observées

### PLAT

Critères les plus utiles dans les données :

- `value_cote` : précision Render 19.5%, corrélation locale **0.371**
- `forme_recente` : précision Render **26.3%**, corrélation locale **0.327**
- `gains` : corrélation locale **0.331**
- `terrain` : précision Render **22.9%**, corrélation locale 0.134

Critères faibles ou suspects :

- `entraineur` : précision Render 13.6%, corrélation locale **-0.217**
- `repos` : précision Render 19.5%, corrélation locale **-0.087**
- `age` : corrélation locale **-0.023**

### TROT_ATTELE

Critères les plus utiles :

- `value_cote` : précision Render **32.5%**, corrélation locale **0.505**
- `forme_recente` : précision Render 23.9%, corrélation locale **0.326**
- `terrain` : précision Render 22.2%, corrélation locale **0.273**
- `distance` : précision Render 23.9%, corrélation locale **0.205**

Critères faibles ou surpondérés :

- `corde` : précision Render 16.2%, corrélation locale **0.087**
- `regularite` : précision Render 15.4%, corrélation locale **0.000**
- `entraineur` : précision Render 19.7%, corrélation locale **-0.037**
- `repos` : précision Render 11.1%, corrélation locale **-0.098**

### TROT_MONTE

Avec prudence vu l’échantillon :

- `value_cote` très fort en Render (précision 35.3%, auto weight 34.2%)
- `distance`, `forme_recente`, `gains` semblent utiles
- `corde` et `regularite` apparaissent faibles / instables

## 3.2 Écart entre poids experts et poids auto-calibrés

### PLAT — dérive problématique du mode auto

Poids auto actuels relevés via `/api/stats/calibration` :

- forme 20.5% vs expert 32.0%
- cote 19.3% vs expert 15.0%
- terrain 16.4% vs expert 8.0%
- gains 12.0% vs expert 5.0%
- partants 17.5% vs expert 2.0%
- jockey **0.0%**
- repos **0.0%**

Lecture :

- le calibrage auto **sous-pondère la forme**
- il **sur-pondère énormément `partants`**
- il annule des critères structurels utiles comme `jockey`
- cela est cohérent avec le fait que **l’auto fasse moins bien que l’expert en plat**

### TROT_ATTELE — auto utile mais trop extrême

Poids auto actuels :

- cote 26.7% vs expert 14.0%
- forme 17.8% vs expert 26.0%
- distance 14.0% vs expert 5.0%
- partants 14.9% vs expert 2.0%
- corde 5.4% vs expert 16.0%
- régularité **0.0%** vs expert 13.0%
- entraîneur **0.0%** vs expert 6.0%

Lecture :

- l’auto améliore bien les résultats, donc il faut **conserver l’idée**
- mais il pousse trop loin certains effets :
  - **cote** trop dominante
  - **partants** trop haut
  - **corde** et **régularité** probablement trop abaissées à 0

### TROT_MONTE — auto trop dépendant de la cote

Poids auto actuels :

- cote 34.2%
- forme 17.1%
- gains 16.3%
- distance 16.2%
- corde 0.0%
- régularité 0.0%
- jockey 0.0%

Lecture :

- le mode auto est trop agressif sur `value_cote`
- il retire trop de structure métier
- cohérent avec sa sous-performance face à l’expert

---

## 4) Analyse des patterns

## 4.1 Le modèle est-il meilleur sur favoris ou outsiders ?

### TROT_ATTELE (fenêtre locale)

Taux de victoire du **top1 IA** selon sa cote :

| Cote top1 IA | Win rate |
|---|---:|
| <= 3 | 50.0% |
| 3 à 8 | 40.0% |
| > 8 | 20.0% |

Mais le top1 IA est un outsider (>8) dans **47.6%** des courses de trot attelé, ce qui est **trop fréquent**.

### PLAT (fenêtre locale)

| Cote top1 IA | Win rate |
|---|---:|
| <= 3 | 0.0% |
| 3 à 8 | 16.7% |
| > 8 | 0.0% |

Le problème du plat n’est donc pas seulement “trop de favoris” ou “trop d’outsiders” : c’est surtout un **mauvais arbitrage des critères**.

## 4.2 Les value bets sont-elles rentables ?

### Value bets actuelles par discipline (fenêtre locale)

| Discipline | Count | Win rate | Top3 rate | ROI gagnant seul |
|---|---:|---:|---:|---:|
| PLAT | 19 | 10.5% | 42.1% | **-51.1%** |
| TROT_ATTELE | 86 | 15.1% | 44.2% | **+9.4%** |
| TROT_MONTE | 17 | 17.6% | 41.2% | +78.8%* |
| HAIE | 8 | 0.0% | 25.0% | -100.0% |
| STEEPLE | 4 | 25.0% | 50.0% | +27.5%* |

\* échantillon faible.

### Effet d’un relèvement du seuil minimum de score des value bets

#### TROT_ATTELE

| Seuil `VALUE_BET_MIN_SCORE` | Count | Win rate | ROI gagnant seul |
|---|---:|---:|---:|
| 50 | 86 | 15.1% | +9.4% |
| 55 | 61 | 16.4% | +0.5% |
| 60 | 37 | 18.9% | **+32.7%** |
| 65 | 13 | **30.8%** | **+100.0%** |

Lecture :

- relever le seuil réduit fortement le volume
- mais **améliore nettement la qualité**
- `60` paraît un bon compromis ; `65` devient trop sélectif

#### PLAT

| Seuil | Count | Win rate | ROI gagnant seul |
|---|---:|---:|---:|
| 50 | 19 | 10.5% | -51.1% |
| 55 | 8 | 12.5% | -38.7% |
| 60 | 2 | 0.0% | -100.0% |

Lecture :

- en plat, le problème n’est pas seulement le seuil : la logique de détection produit trop de faux positifs
- il faut être **nettement plus strict** en plat, voire désactiver opérationnellement les value bets tant que le recalibrage n’est pas fait

## 4.3 `score_global` est-il un bon prédicteur du classement réel ?

Moyenne locale de corrélation de Spearman :

- `score_global` : **0.320**
- `score_sans_cote` : **0.284**

Interprétation :

- le score global contient bien de l’information utile
- mais la hiérarchie reste **modérément prédictive**, pas suffisamment forte pour soutenir des paris combinés ambitieux à fort ordre
- cela est cohérent avec les résultats très faibles sur :
  - tiercé ordre
  - quarté ordre / désordre
  - trio ordre
  - super4

---

## 5) Recommandations concrètes et chiffrées

## 5.1 Recommandations prioritaires

### A. PLAT — revenir à une logique plus “forme + gains”, moins “effets secondaires”

#### Recommandation de poids expert PLAT

Proposition :

| Critère | Actuel | Proposé |
|---|---:|---:|
| forme_recente | 0.32 | **0.35** |
| value_cote | 0.15 | **0.16** |
| jockey | 0.12 | **0.10** |
| entraineur | 0.08 | **0.05** |
| distance | 0.10 | **0.09** |
| terrain | 0.08 | **0.08** |
| repos | 0.05 | **0.03** |
| gains | 0.05 | **0.09** |
| age | 0.03 | **0.02** |
| partants | 0.02 | **0.01** |
| hippodrome | 0.00 | **0.02** |

Justification :

- `forme_recente` et `gains` sont les deux signaux les plus cohérents dans les données récentes
- `entraineur`, `repos` et `age` montrent peu de valeur récente
- `partants` ne doit surtout pas suivre la dérive auto constatée à 17.5%

Impact attendu :

- **réduire les faux top1 en plat**
- **remonter la stabilité du top1 top3**
- éviter que le plat soit pénalisé par des critères peu discriminants

#### Recommandation de calibration auto PLAT

- **ne pas activer automatiquement les poids auto actuels en PLAT**
- conserver **expert comme mode par défaut**
- si recalibration future :
  - **capper `partants` à 0.05 max**
  - **capper `value_cote` à 0.18 max**
  - **forcer `forme_recente` à un plancher de 0.28**
  - **forcer `jockey` à un plancher de 0.06**

### B. TROT_ATTELE — conserver l’auto, mais le rendre moins extrême

#### Recommandation de poids TROT_ATTELE

Proposition de cible hybride expert/auto :

| Critère | Expert actuel | Auto actuel | Proposé |
|---|---:|---:|---:|
| forme_recente | 0.26 | 0.178 | **0.22** |
| value_cote | 0.14 | 0.267 | **0.20** |
| corde | 0.16 | 0.054 | **0.10** |
| regularite | 0.13 | 0.000 | **0.07** |
| gains | 0.07 | 0.091 | **0.08** |
| recence | 0.08 | 0.062 | **0.07** |
| entraineur | 0.06 | 0.000 | **0.03** |
| distance | 0.05 | 0.140 | **0.10** |
| age | 0.03 | 0.061 | **0.05** |
| partants | 0.02 | 0.149 | **0.08** |

Justification :

- l’auto a raison de renforcer `value_cote`, `distance`, `age`, `partants`
- mais il va trop loin en annulant `regularite` et `corde`
- le récent ROI positif des value bets en trot attelé montre qu’il faut **garder l’agressivité**, mais de façon contrôlée

Impact attendu :

- préserver l’avantage actuel de l’auto
- réduire les faux positifs sur outsiders
- stabiliser la hiérarchie top3/top5

### C. TROT_MONTE — éviter la surdépendance à la cote

#### Recommandation de poids TROT_MONTE

| Critère | Actuel expert | Auto actuel | Proposé |
|---|---:|---:|---:|
| forme_recente | 0.27 | 0.171 | **0.25** |
| value_cote | 0.14 | 0.342 | **0.18** |
| corde | 0.13 | 0.000 | **0.08** |
| regularite | 0.11 | 0.000 | **0.07** |
| gains | 0.07 | 0.163 | **0.10** |
| recence | 0.08 | 0.027 | **0.06** |
| jockey | 0.08 | 0.000 | **0.08** |
| entraineur | 0.05 | 0.087 | **0.06** |
| distance | 0.04 | 0.162 | **0.08** |
| age | 0.03 | 0.048 | **0.04** |

Justification :

- l’expert fait actuellement au moins aussi bien que l’auto
- il faut **réduire la dépendance à la cote**
- `gains` et `distance` méritent une hausse modérée

## 5.2 Recommandations sur les value bets

### Réglage global minimal

Proposition :

- `VALUE_BET_MIN_SCORE` : **50 → 60**
- `VALUE_BET_FACTOR` : **1.30 → 1.38**

Justification :

- en trot attelé, le seuil 60 réduit le volume mais améliore clairement la qualité
- en plat, cela élimine une partie des faux positifs les plus faibles

### Réglage idéal par discipline

Si le produit peut aller vers des seuils par discipline :

| Discipline | `MIN_SCORE` proposé | `FACTOR` proposé |
|---|---:|---:|
| PLAT | **62** | **1.45** |
| TROT_ATTELE | **60** | **1.30** |
| TROT_MONTE | **58** | **1.32** |
| HAIE/STEEPLE | **62** | **1.40** |

Justification :

- **PLAT** : value bets trop permissives aujourd’hui
- **TROT_ATTELE** : value bets exploitables, pas besoin de durcir trop le facteur
- **Obstacle** : faible échantillon, mieux vaut filtrer davantage par prudence

## 5.3 Recommandations logiques

### D. Encadrer la calibration auto

Le problème principal n’est pas la calibration en soi, mais l’absence de garde-fous.

Je recommande :

1. **Plancher / plafond par critère**
   - ex. `partants <= 0.08`
   - `value_cote <= 0.22`
   - `forme_recente >= 0.20`

2. **Shrinkage vers les poids experts**
   - formule recommandée :  
     `poids_final = 0.7 * poids_auto + 0.3 * poids_expert`

3. **Ne calibrer qu’au-delà d’un vrai seuil de robustesse**
   - actuel : 10 courses mini
   - recommandé pour un mode réellement actif :
     - **PLAT / TROT_ATTELE : 40+ courses**
     - **TROT_MONTE : 20+ courses**
     - **Obstacle : 20+ courses**

### E. Réduire la fréquence des top picks outsiders en trot

Constat :

- en TROT_ATTELE, le top1 IA est outsider (>8) dans **47.6%** des courses récentes
- son taux de victoire n’est alors que de **20%**

Recommandation :

- pénaliser légèrement les outsiders top1 quand :
  - `cote > 12`
  - et `forme_recente < 60`
  - et `regularite < 55`

Objectif :

- garder les bons outsiders
- éviter les surestimations structurelles

### F. Être très prudent sur les paris combinés ordonnés

Les taux actuels sont trop faibles pour recommander fortement :

- tiercé ordre
- quarté ordre
- trio ordre
- super4

Le scoring actuel est plus pertinent pour :

- gagnant
- placé
- 2sur4
- multi 6/7

---

## 6) Ajustements recommandés, par priorité d’implémentation

### Priorité 1

1. **Conserver PLAT en mode expert**
2. **Conserver TROT_ATTELE en auto**
3. **Remonter `VALUE_BET_MIN_SCORE` à 60**
4. **Remonter `VALUE_BET_FACTOR` à 1.38**

### Priorité 2

5. **Réviser les poids PLAT** vers plus de `forme_recente` et `gains`
6. **Réduire `entraineur`, `repos`, `age` en PLAT**
7. **Réduire la domination de `value_cote` en TROT_MONTE**
8. **Réintroduire un poids non nul à `regularite` et `corde` en TROT_ATTELE**

### Priorité 3

9. **Encadrer la calibration auto avec des caps/planchers**
10. **Passer à des seuils value bet par discipline**

---

## 7) Synthèse exécutive

### Ce qui marche

- **TROT_ATTELE** est aujourd’hui la discipline la plus exploitable
- le **mode auto** apporte un vrai plus en trot attelé
- le **score global** reste utile pour ordonner les chevaux, surtout sur des paris simples

### Ce qui pénalise les bilans

- **PLAT** : auto-calibration moins bonne que l’expert
- **value bets trop permissives**, surtout en plat
- **calibration auto sans garde-fous**, qui surpondère parfois des critères secondaires
- trop d’ambition sur les **paris ordonnés**

### Décision concrète recommandée

Si un seul lot d’ajustements devait être testé en premier :

1. **PLAT** : garder le mode expert, avec poids proposés  
2. **TROT_ATTELE** : garder l’auto, mais avec version “bridée”  
3. **VALUE_BET_MIN_SCORE = 60**  
4. **VALUE_BET_FACTOR = 1.38**  
5. **Pas d’activation de recommandations fortes sur trio/tiercé/quarté ordre**

---

## 8) Estimation qualitative d’impact

Estimation prudente, non garantie, basée sur les écarts observés :

- **PLAT**
  - baisse des faux positifs top1 et value bets
  - impact attendu : **amélioration modérée** du bilan, surtout via réduction des mauvaises sélections

- **TROT_ATTELE**
  - conservation de la surperformance actuelle de l’auto
  - impact attendu : **amélioration modérée à forte** sur le bilan des value bets si le seuil passe à 60

- **Global**
  - moins de volume, mais **meilleure qualité moyenne**
  - orientation plus saine pour les bilans futurs

---

## 9) Recommandation finale

La meilleure trajectoire n’est pas de “forcer davantage la cote”, mais de :

- **mieux borner la calibration**
- **resserrer la détection value bet**
- **traiter le PLAT séparément du trot**

En l’état des données, la recommandation la plus solide est :

- **PLAT = expert**
- **TROT_ATTELE = auto contrôlé**
- **TROT_MONTE = expert**
- **value bets plus strictes**
