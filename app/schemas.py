from datetime import datetime
from pydantic import BaseModel


class ParticipantSchema(BaseModel):
    id: int
    num_pmu: int
    nom: str
    jockey: str
    entraineur: str
    proprietaire: str
    cote_actuelle: float | None
    cote_initiale: float | None
    musique: str
    poids: float | None
    age: int
    sexe: str
    provenance: str
    score_global: float
    score_forme: float
    score_cote: float
    score_jockey: float
    score_entraineur: float
    score_distance: float
    score_terrain: float
    score_repos: float = 0.0
    score_partants: float = 0.0
    score_hippodrome: float = 0.0
    score_poids: float = 0.0
    # Critères trot
    score_corde: float = 50.0
    score_regularite: float = 50.0
    score_recence: float = 50.0
    is_value_bet: bool
    confiance: str
    explication: str
    position_arrivee: int | None = None

    class Config:
        from_attributes = True


class CourseSchema(BaseModel):
    id: int
    num_ordre: int
    libelle: str
    libelle_court: str
    heure_depart: datetime | None
    distance: int
    discipline: str
    specialite: str
    terrain: str
    penetrometre_valeur: float | None
    nombre_partants: int
    montant_prix: float
    statut: str
    statut_resultat: str = "EN_COURS"
    condition_age: str
    condition_sexe: str
    paris_disponibles: str = ""
    participants_loaded: bool
    reunion_id: int

    class Config:
        from_attributes = True


class CourseDetailSchema(CourseSchema):
    participants: list[ParticipantSchema] = []
    hippodrome: str = ""
    top_pick: ParticipantSchema | None = None
    value_bets: list[ParticipantSchema] = []


class ReunionSchema(BaseModel):
    id: int
    num_officiel: int
    hippodrome_code: str
    hippodrome_libelle: str
    pays: str
    courses: list[CourseSchema] = []

    class Config:
        from_attributes = True


class DashboardSchema(BaseModel):
    date: str
    nb_reunions: int
    nb_courses: int
    nb_value_bets: int
    top_picks: list[ParticipantSchema] = []
    reunions: list[ReunionSchema] = []


class DailyStatsSchema(BaseModel):
    date: str
    nb_courses: int
    nb_value_bets: int
    nb_top_picks_correct: int
    nb_courses_finished: int


# ---- F3 : Paris ----

class BetCheval(BaseModel):
    numero: int
    nom: str
    cote: float | None = None


class BetCreate(BaseModel):
    type_pari: str  # GAGNANT | PLACE | COUPLE | TIERCE | DEUX_SUR_QUATRE
    montant: float = 2.0
    course_id: int | None = None
    course_label: str = ""
    hippodrome: str = ""
    chevaux: list[BetCheval]


class BetSchema(BaseModel):
    id: int
    created_at: datetime
    type_pari: str
    montant: float
    statut: str
    gain_reel: float | None
    course_id: int | None
    course_label: str
    hippodrome: str
    chevaux: list[BetCheval] = []

    class Config:
        from_attributes = True


# ---- F2 : Scoring ----

class ScoringAccuracySchema(BaseModel):
    critere: str
    poids: float
    precision: float
    nb_samples: int


class ScoringAccuracyByDisciplineSchema(BaseModel):
    discipline: str
    critere: str
    poids: float
    precision: float
    nb_samples: int


# ---- F3 : Suggestions combos ----

class CourseSuggestionsSchema(BaseModel):
    gagnant: ParticipantSchema | None = None
    place: ParticipantSchema | None = None
    couple: list[ParticipantSchema] = []
    tierce: list[ParticipantSchema] = []
    deux_sur_quatre: list[ParticipantSchema] = []
