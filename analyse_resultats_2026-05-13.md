# Analyse résultats PMU — 13/05/2026

## Périmètre

Analyse réalisée **sans modifier le code**, à partir de :

- l’API Render protégée :
  - `POST /api/login`
  - `GET /api/courses`
  - `GET /api/courses/{id}`
  - `GET /api/stats/scoring`
  - `GET /api/stats/calibration`
  - `GET /api/bilan?periode=today&discipline=PLAT`
- la base locale `pmu_analyzer.db`
- la lecture du moteur de scoring et des routes :
  - `app/config.py`
  - `app/scoring.py`
  - `app/routers/courses.py`
  - `app/routers/stats_router.py`
  - `app/routers/bilan_router.py`
- le rapport existant `analyse_pronostics_2026-05-12.md`

## Résumé exécutif

- Le **13/05/2026 a été très mauvais en PLAT**, surtout sur les top-picks.
- Sur les **19 courses PLAT terminées** du jour :
  - **top-1 exposé via `score_global`** : **1/19 = 5,3%**
  - **top-1 expert** : **2/19 = 10,5%**
  - **top-1 sans cote** : **3/19 = 15,8%**
- Sur les courses PLAT avec pari **GAGNANT** disponible, l’API bilan confirme :
  - **auto** : **0/10**
  - **expert** : **1/10**
  - **sans cote** : **2/10**
- Le pattern principal du jour : le modèle a **sur-favorisé la forme récente, la cote et la distance**, alors que les gagnants réels étaient souvent **moins “beaux” sur le papier** mais **plus frais** ou plus opportunistes.
- Point important : les stats globales disent que **PLAT devrait être servi en mode expert**, mais les détails courses/top-picks retournent encore un `score_global` issu de l’**auto** quand des poids calibrés existent. Il y a donc un **décalage entre le mode recommandé et le mode effectivement exposé**.

---

## 1) Collecte du jour

### Courses PLAT terminées le 13/05/2026

Total détecté via l’API : **19**

Répartition principale observée :

- **Vichy** : 8 courses
- **Happy Valley (HK)** : 9 courses
- **San Isidro (ARG)** : 2 courses

### Qualité des données du jour

Le 13/05 présente plusieurs limites qui ont un impact direct sur l’analyse :

- `terrain` est **vide sur 19/19 courses PLAT** du jour
- de nombreuses courses étrangères ont des `cote_actuelle` **null**
- plusieurs critères sont souvent quasi neutres à **50**
  - `score_jockey`
  - `score_partants`
  - `score_hippodrome`

Conséquence : une partie du scoring PLAT du jour s’est jouée sur peu de signaux réellement discriminants, surtout :

- `forme_recente`
- `value_cote` quand disponible
- `distance`
- `gains`

---

## 2) Pronostics vs résultats — focus PLAT

## 2.1 Bilan global du jour

### Top-1 PLAT du 13/05

| Mode analysé | Corrects | Total | Taux |
|---|---:|---:|---:|
| `score_global` (auto exposé) | 1 | 19 | **5,3%** |
| Expert | 2 | 19 | **10,5%** |
| Sans cote | 3 | 19 | **15,8%** |

### Bilan API PLAT du jour sur les courses “GAGNANT” évaluables

| Mode | Gagnés | Evaluées | Taux |
|---|---:|---:|---:|
| Auto | 0 | 10 | **0,0%** |
| Expert | 1 | 10 | **10,0%** |
| Sans cote | 2 | 10 | **20,0%** |

Lecture :

- la **cote a plutôt dégradé** le résultat PLAT aujourd’hui
- l’**expert** fait mieux que l’auto
- le **sans cote** fait mieux que les deux, ce qui indique que le modèle a probablement **trop suivi le marché** sur cette journée

## 2.2 Le modèle favorise-t-il trop les favoris ?

### Favoris réels du jour

- taux de victoire du **favori de marché** sur les courses du jour : **12,5%**

### Top-pick du modèle (`score_global`)

- top-pick = favori de marché dans **31,6%** des courses
- parmi les top-picks cotés :
  - **7** top-picks à **<= 3/1**
  - **1** top-pick à **> 8/1**
- résultat :
  - **0/7** gagnant chez les top-picks `<= 3`
  - **0/1** gagnant chez les top-picks `> 8`

Conclusion :

- le problème n’est pas “le modèle joue trop d’outsiders”
- le problème du jour est plutôt : **quand il a choisi un favori, c’était souvent le mauvais favori**
- en pratique, le moteur a **sur-récompensé des chevaux très propres sur la forme/cote**, mais pas forcément les vrais gagnants du jour

## 2.3 Types de courses où le modèle s’est le plus trompé

### Par nombre de partants

| Taille de champ | Corrects | Total | Taux |
|---|---:|---:|---:|
| `<= 10` partants | 0 | 5 | **0,0%** |
| `11-13` partants | 1 | 8 | **12,5%** |
| `14+` partants | 0 | 6 | **0,0%** |

Lecture :

- journée mauvaise partout
- mais **très faible** sur les petits champs et les gros pelotons
- seul léger mieux sur les champs moyens (`11-13`)

### Par hippodrome / bloc de courses

- **Vichy** : **0/8**
- **Happy Valley** : **1/9**
- **San Isidro** : **0/2**

Deux patterns distincts apparaissent :

1. **Vichy**  
   Le modèle a souvent surjoué des **ultra-favoris** à 1.1–1.7 qui n’ont pas gagné.

2. **Happy Valley / San Isidro**  
   Beaucoup de données sont **pauvres ou neutres** :
   - cotes absentes
   - terrain absent
   - jockey/hippodrome peu discriminants  
   Le scoring retombe alors surtout sur forme + distance + gains.

---

## 3) Courses ratées — pronostiqué 1er vs gagnant réel

Ci-dessous, les **18 courses ratées** du jour en PLAT avec le top-pick `score_global`.

| Course | Hippodrome | Prono 1er | Cote | Pos. | Gagnant réel | Cote gagnant | Écart score |
|---|---|---|---:|---:|---|---:|---:|
| PRIX DES REVES D'OR - JACQUES BOUCHARA | Vichy | MAIAKOVSKA | 1.1 | 3 | VALENTINA BELLA | 61.0 | +18.66 |
| PRIX DU GRAND PORT | Vichy | MAPLE GIRL | 1.1 | 2 | FERNANDO | 5.6 | +8.55 |
| PRIX DE LA GRANDE CHARTREUSE | Vichy | SECRET FEELING | 1.1 | 12 | BOOMERANG | 6.2 | +14.11 |
| PRIX NORTH COL | Vichy | ITAEWON | 1.1 | 4 | BOIS REGNY | 16.0 | +27.19 |
| PRIX D'ABREST | Vichy | PURPLE BAY | 1.5 | 4 | TOUNSBY | 9.6 | +25.36 |
| PRIX NO RISK AT ALL | Vichy | ARGYRON | 10.0 | 11 | WAITARA | 22.0 | +15.13 |
| PRIX CIRRUS DES AIGLES | Vichy | MAJESTIC HILL | 1.2 | 6 | GOOD QUESTION | 16.0 | +27.29 |
| PRIX MARILDO | Vichy | JARDIN BLEU | 1.7 | 4 | POET'S BLACK | 1.7 | +1.57 |
| CHANTILLY HANDICAP - SECTION 2 | Happy Valley | WORLD HERO | n/d | 3 | NEBRASKAN | n/d | +8.76 |
| THE FRENCH MAY TROPHY (HANDICAP) | Happy Valley | ALL ROUND WINNER | n/d | 3 | ROMANTIC GLADIATOR | n/d | +11.88 |
| SAINT-CLOUD HANDICAP - SECTION 1 | Happy Valley | MEGA MASTERMIND | n/d | 9 | GENERAL REDWOOD | n/d | +13.72 |
| THE FRANCE GALOP CUP (HANDICAP) | Happy Valley | ACE WAR | n/d | 3 | LIVEANDLETLIVE | n/d | +4.24 |
| SAINT-CLOUD HANDICAP - SECTION 2 | Happy Valley | RUN RUN TIMING | n/d | 3 | THE AZURE | n/d | +19.97 |
| CHANTILLY HANDICAP - SECTION 1 | Happy Valley | VIGOR EYE | n/d | 12 | LEADING AGILITY | n/d | +15.07 |
| DEAUVILLE HANDICAP | Happy Valley | AURIO | n/d | 3 | MOTOR | n/d | +9.48 |
| PARISLONGCHAMP HANDICAP | Happy Valley | SPEED DRAGON | n/d | 8 | PACKING ANGEL | n/d | +13.90 |
| PREMIO ESPECIAL SEDUCTOR | San Isidro | FARRA GIRL | n/d | 2 | REINA CASADA | n/d | +2.23 |
| PREMIO MASTER COCKTAIL 2023 (ALTERNATIVA) (OPCIONAL) | San Isidro | SERENA AMBICION | n/d | n/d | SUME ROAD | n/d | +1.15 |

`Écart score` = `score_top_pick - score_gagnant_réel`

Lecture :

- les plus gros ratés du jour se concentrent à **Vichy**
- sur plusieurs courses, le modèle donnait au top-pick **10 à 27 points** d’avance sur le gagnant réel
- cela indique un **surclassement artificiel** de certains chevaux “propres” sur les critères dominants

---

## 4) Analyse des critères — gagnants réels vs chevaux pronostiqués

## 4.1 Écarts moyens du jour (gagnant réel moins top-pick `score_global`)

| Critère | Moyenne gagnants | Moyenne top-picks | Delta gagnant - prono |
|---|---:|---:|---:|
| forme_recente | 53.10 | 70.96 | **-17.86** |
| value_cote | 35.34 | 58.36 | **-23.01** |
| jockey | 50.00 | 50.00 | 0.00 |
| entraineur | 53.00 | 54.47 | -1.47 |
| distance | 49.95 | 68.16 | **-18.21** |
| terrain | 49.16 | 56.11 | -6.95 |
| repos | 58.11 | 55.58 | **+2.53** |
| partants | 51.84 | 51.84 | 0.00 |
| hippodrome | 50.00 | 50.00 | 0.00 |
| gains | 54.07 | 62.53 | -8.46 |
| age | 61.32 | 62.63 | -1.32 |

### Lecture directe

Les critères les plus **sur-évalués par rapport aux gagnants réels** aujourd’hui sont :

1. **`value_cote`** : -23.01
2. **`distance`** : -18.21
3. **`forme_recente`** : -17.86
4. **`gains`** : -8.46
5. **`terrain`** : -6.95

Le seul critère un peu **sous-estimé** aujourd’hui :

- **`repos`** : +2.53

### Interprétation métier

- **Forme récente trop forte** : le modèle a préféré des chevaux très lisibles sur la musique, mais cette journée a produit beaucoup de gagnants moins “propres”.
- **Cote trop influente** : plusieurs top-picks étaient des énormes favoris battus.
- **Distance trop sur-valorisée** : le critère a renforcé des favoris logiques sans réellement séparer les gagnants du jour.
- **Terrain non pertinent aujourd’hui** : comme `terrain` était vide sur toutes les courses PLAT du jour, ce score n’était pas réellement informatif.
- **Repos légèrement sous-estimé** : les gagnants réels étaient en moyenne un peu mieux notés sur la fraîcheur.

## 4.2 Ce que montrent quelques ratés emblématiques

### Vichy — favori surcoté par la cote et la forme

Exemples marquants :

- **MAIAKOVSKA (1.1)** battue par **VALENTINA BELLA (61.0)**
- **SECRET FEELING (1.1)** battue par **BOOMERANG (6.2)**
- **MAJESTIC HILL (1.2)** battu par **GOOD QUESTION (16.0)**

Dans ces courses, le différentiel vient surtout de :

- `score_cote`
- `score_forme`
- parfois `score_distance`

### Happy Valley — scoring trop “mécanique” faute de signaux riches

Sur Happy Valley :

- cotes souvent absentes
- terrain absent
- scores jockey/hippodrome peu discriminants

Le moteur a donc essentiellement arbitré via :

- forme
- distance
- gains

et a souvent raté des gagnants moins bien notés sur ces trois dimensions.

---

## 5) Les poids experts PLAT actuels vs ce que disent les données

### Poids experts actuels

| Critère | Poids expert |
|---|---:|
| forme_recente | 0.35 |
| value_cote | 0.16 |
| jockey | 0.10 |
| entraineur | 0.05 |
| distance | 0.09 |
| terrain | 0.08 |
| repos | 0.03 |
| gains | 0.09 |
| age | 0.02 |
| partants | 0.01 |
| hippodrome | 0.02 |

### Poids auto actuellement calibrés pour PLAT

| Critère | Poids auto |
|---|---:|
| forme_recente | 0.2574 |
| value_cote | 0.1831 |
| jockey | 0.0617 |
| entraineur | 0.0261 |
| distance | 0.1049 |
| terrain | 0.1462 |
| repos | 0.0093 |
| gains | 0.1167 |
| age | 0.0062 |
| partants | 0.0822 |
| hippodrome | 0.0062 |

### Lecture critique

#### Côté expert

Le PLAT expert semble encore **trop lourd sur** :

- `forme_recente`
- `value_cote`
- `distance`

et probablement **pas assez sensible à la fraîcheur** (`repos`).

#### Côté auto

Le PLAT auto reste problématique, car il :

- sur-pondère encore plus `value_cote`
- sur-pondère `terrain` alors que les données terrain sont souvent pauvres
- sur-pondère `partants`
- sous-pondère fortement :
  - `jockey`
  - `entraineur`
  - `repos`
  - `age`
  - `hippodrome`

Et surtout :

- **l’historique global PLAT Render confirme que l’auto fait moins bien que l’expert**
  - **expert : 18,2% top-1**
  - **auto : 16,1% top-1**
  - **sans cote : 18,2% top-1**

---

## 6) Comparaison avec les jours précédents depuis le 08/05

## 6.1 Ce n’est pas seulement “une mauvaise journée”

### Fenêtre locale 08/05 → 11/05 (rapport et DB locale)

PLAT sur la fenêtre récente locale :

- **14 courses**
- **14,3%** de top-1 correct
- **35,7%** de top-1 dans le top-3

### Rapport du 12/05

Le rapport `analyse_pronostics_2026-05-12.md` concluait déjà :

- **PLAT sous-performe clairement**
- les **value bets PLAT détruisent de la valeur**
- le mode **auto dégrade** le PLAT par rapport à l’expert

### Évolution hebdomadaire Render (PLAT, pari GAGNANT)

| Semaine | Auto | Expert | Sans cote |
|---|---:|---:|---:|
| 2026-S19 | 21,5% | 22,8% | 20,3% |
| 2026-S20 | 10,4% | 12,5% | **16,7%** |

Lecture :

- la semaine en cours est **nettement plus faible** que la précédente
- et dans cette semaine faible, le **sans cote résiste mieux**
- le problème PLAT n’est donc **pas isolé au 13/05**
- le pattern le plus net depuis le 08/05 est :
  - **PLAT faible**
  - **auto pas au niveau**
  - **sensibilité à la cote trop forte dans les mauvais jours**

## 6.2 Ce qui semble structurel vs conjoncturel

### Tendance probablement structurelle

- le **PLAT auto** est moins bon que l’expert
- la **forme récente** et la **cote** dominent trop souvent les arbitrages finaux
- quand la journée devient piégeuse, le moteur manque de robustesse

### Tendance probablement conjoncturelle au 13/05

- journée avec **terrain absent partout**
- plusieurs courses étrangères avec **cotes manquantes**
- bloc Vichy très défavorable aux gros favoris

Donc :

- **oui, la journée a été mauvaise**
- mais **non, ce n’est pas uniquement un accident**
- elle **renforce un défaut déjà visible depuis le 08/05** sur le PLAT

---

## 7) Paramètres mal calibrés identifiés

## 7.1 Les plus suspects aujourd’hui

### 1. `value_cote`

Pourquoi :

- plus gros delta moyen contre les gagnants : **-23.01**
- le sans-cote fait mieux que l’auto et l’expert aujourd’hui
- plusieurs favoris à 1.1–1.7 ont été battus

Diagnostic :

- **sur-calibré à la hausse** dans les journées piégeuses

### 2. `forme_recente`

Pourquoi :

- delta moyen : **-17.86**
- les top-picks du jour étaient souvent “parfaits dans la musique”
- les gagnants ont souvent gagné sans avoir la meilleure musique récente

Diagnostic :

- **sur-pondéré**

### 3. `distance`

Pourquoi :

- delta moyen : **-18.21**
- sur de nombreuses courses ratées, le gagnant avait un `score_distance` plus faible que le top-pick

Diagnostic :

- **sur-utilisé comme critère de confirmation**

### 4. `repos`

Pourquoi :

- seul critère avec delta positif : **+2.53**

Diagnostic :

- **légèrement sous-pondéré**

### 5. `terrain`

Pourquoi :

- absent dans la donnée source du jour

Diagnostic :

- pas forcément “mal calibré” en absolu
- mais **non pertinent aujourd’hui**
- il devrait idéalement être **neutralisé quand le terrain n’est pas renseigné**

## 7.2 Critères peu exploitables sur cette journée

Ces critères ont peu aidé le 13/05 :

- `jockey`
- `partants`
- `hippodrome`

Non pas forcément parce qu’ils sont faux, mais parce que les scores retournés étaient souvent **quasi constants**.

---

## 8) Propositions d’ajustement — prudentes et chiffrées

## 8.1 Décision opérationnelle immédiate

### Recommandation

En **PLAT**, pour les prochains jours, utiliser **Expert** par défaut, voire **Sans cote** en contrôle secondaire.

Justification :

- historique Render PLAT :
  - expert **18,2%**
  - auto **16,1%**
- 13/05 :
  - auto **5,3%**
  - expert **10,5%**
  - sans cote **15,8%**

## 8.2 Ajustements de poids à tester en priorité

Je recommande **un test prudent**, pas un basculement brutal.

### Proposition de variations ciblées

| Critère | Actuel | Test conseillé | Commentaire |
|---|---:|---:|---|
| forme_recente | 0.35 | **0.30 à 0.32** | à alléger |
| value_cote | 0.16 | **0.11 à 0.13** | à alléger nettement |
| distance | 0.09 | **0.06 à 0.07** | à alléger |
| repos | 0.03 | **0.04 à 0.05** | à renforcer légèrement |
| gains | 0.09 | **0.09 à 0.10** | conserver ou monter très légèrement |
| terrain | 0.08 | **0.08** | conserver, mais neutraliser si absent |
| jockey | 0.10 | **0.10** | pas de signal suffisant pour changer |
| entraineur | 0.05 | **0.04 à 0.05** | légère baisse possible |
| age | 0.02 | **0.02 à 0.03** | faible impact |
| partants | 0.01 | **0.01** | inchangé |
| hippodrome | 0.02 | **0.02** | inchangé |

## 8.3 Scénario concret de test A

Si on veut un seul jeu de poids à tester en bac à sable :

| Critère | Poids test A |
|---|---:|
| forme_recente | **0.31** |
| value_cote | **0.12** |
| jockey | **0.10** |
| entraineur | **0.05** |
| distance | **0.07** |
| terrain | **0.08** |
| repos | **0.05** |
| gains | **0.10** |
| age | **0.03** |
| partants | **0.01** |
| hippodrome | **0.02** |

Somme = **0.94**

Les **0.06 restants** devraient idéalement être **redistribués dynamiquement** uniquement vers les critères réellement renseignés du jour, par exemple :

- `gains`
- `repos`
- `jockey`

plutôt que d’être figés sur des critères absents ou neutres.

Autrement dit :

- je recommande **moins une simple retouche statique**
- et **plus une baisse des poids dominants + neutralisation des critères non renseignés**

## 8.4 Ce qu’il ne faut pas faire

- **Ne pas** monter fortement `terrain` à partir du 13/05 : le terrain était vide partout.
- **Ne pas** sur-réagir à une seule journée en écrasant complètement `forme_recente` ou `value_cote`.
- **Ne pas** laisser le PLAT continuer à exposer implicitement l’auto si l’historique recommande l’expert.

---

## 9) Point important de serving / cohérence produit

L’analyse du code montre une incohérence fonctionnelle :

- `stats/calibration` indique pour **PLAT** : **`active_mode = expert`**
- mais dans `app/scoring.py`, `score_global` prend **l’auto** dès qu’un poids calibré existe
- et `GET /api/courses/{id}` trie les participants par `score_global`

Conséquence :

- la discipline **PLAT est historiquement recommandée en expert**
- mais les listes/top-picks exposées côté course peuvent encore être **auto**

Sur une journée comme le 13/05, ce décalage peut expliquer une partie du ressenti utilisateur :

- les statistiques disent “expert”
- l’affichage concret peut encore pousser “auto”

---

## Conclusion

### Ce que disent les données du 13/05

- très mauvaise journée **PLAT**
- le moteur a surtout **sur-noté** :
  - `value_cote`
  - `forme_recente`
  - `distance`
- le critère `repos` semble **un peu sous-estimé**
- `terrain` n’a **pas été pertinent** aujourd’hui faute de donnée

### Ce que disent les jours précédents depuis le 08/05

- le 13/05 n’est **pas un simple accident isolé**
- il **prolonge une faiblesse déjà visible du PLAT**
- le mode **auto** reste moins robuste que l’**expert** en PLAT

### Recommandation prioritaire

1. **Servir le PLAT en expert**, pas en auto, tant que l’écart historique persiste  
2. **Alléger** `forme_recente`, `value_cote` et `distance`  
3. **Renforcer légèrement** `repos`  
4. **Neutraliser les critères absents** (`terrain`, parfois `cote`) au lieu de les laisser biaiser le score global
