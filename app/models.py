from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Reunion(Base):
    __tablename__ = "reunions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date_str: Mapped[str] = mapped_column(String(8), index=True)  # DDMMYYYY
    num_officiel: Mapped[int] = mapped_column(Integer)
    num_externe: Mapped[int] = mapped_column(Integer)
    hippodrome_code: Mapped[str] = mapped_column(String(20))
    hippodrome_libelle: Mapped[str] = mapped_column(String(100))
    pays: Mapped[str] = mapped_column(String(50), default="FRANCE")

    courses: Mapped[list["Course"]] = relationship("Course", back_populates="reunion", cascade="all, delete-orphan", order_by="Course.num_externe")


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reunion_id: Mapped[int] = mapped_column(ForeignKey("reunions.id"), index=True)
    num_ordre: Mapped[int] = mapped_column(Integer)
    num_externe: Mapped[int] = mapped_column(Integer)
    libelle: Mapped[str] = mapped_column(String(200))
    libelle_court: Mapped[str] = mapped_column(String(100), default="")
    heure_depart: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    distance: Mapped[int] = mapped_column(Integer, default=0)
    discipline: Mapped[str] = mapped_column(String(50), default="PLAT")
    specialite: Mapped[str] = mapped_column(String(50), default="PLAT")
    terrain: Mapped[str] = mapped_column(String(50), default="")
    penetrometre_valeur: Mapped[float | None] = mapped_column(Float, nullable=True)
    nombre_partants: Mapped[int] = mapped_column(Integer, default=0)
    montant_prix: Mapped[float] = mapped_column(Float, default=0.0)
    statut: Mapped[str] = mapped_column(String(50), default="PROGRAMMEE")
    condition_age: Mapped[str] = mapped_column(String(100), default="")
    condition_sexe: Mapped[str] = mapped_column(String(100), default="")
    paris_disponibles: Mapped[str] = mapped_column(String(500), default="")  # JSON list des types de paris
    participants_loaded: Mapped[bool] = mapped_column(Boolean, default=False)
    # F1 : statut résultat
    statut_resultat: Mapped[str] = mapped_column(String(20), default="EN_COURS")  # EN_COURS | TERMINE | ANNULE

    reunion: Mapped["Reunion"] = relationship("Reunion", back_populates="courses")
    participants: Mapped[list["Participant"]] = relationship("Participant", back_populates="course", cascade="all, delete-orphan")
    bets: Mapped[list["Bet"]] = relationship("Bet", back_populates="course", cascade="all, delete-orphan")


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("course_id", "num_pmu", name="uq_participant_course_num"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    num_pmu: Mapped[int] = mapped_column(Integer)
    nom: Mapped[str] = mapped_column(String(100))
    jockey: Mapped[str] = mapped_column(String(100), default="")
    entraineur: Mapped[str] = mapped_column(String(100), default="")
    proprietaire: Mapped[str] = mapped_column(String(100), default="")
    cote_actuelle: Mapped[float | None] = mapped_column(Float, nullable=True)
    cote_initiale: Mapped[float | None] = mapped_column(Float, nullable=True)
    musique: Mapped[str] = mapped_column(String(500), default="")  # historique des performances
    poids: Mapped[float | None] = mapped_column(Float, nullable=True)
    handicap_distance: Mapped[int] = mapped_column(Integer, default=0)
    age: Mapped[int] = mapped_column(Integer, default=0)
    sexe: Mapped[str] = mapped_column(String(10), default="")
    provenance: Mapped[str] = mapped_column(String(100), default="")
    # Scores calculés
    score_global: Mapped[float] = mapped_column(Float, default=0.0)
    score_forme: Mapped[float] = mapped_column(Float, default=0.0)
    score_cote: Mapped[float] = mapped_column(Float, default=0.0)
    score_jockey: Mapped[float] = mapped_column(Float, default=0.0)
    score_entraineur: Mapped[float] = mapped_column(Float, default=0.0)
    score_distance: Mapped[float] = mapped_column(Float, default=0.0)
    score_terrain: Mapped[float] = mapped_column(Float, default=0.0)
    # F2 : nouveaux critères
    score_repos: Mapped[float] = mapped_column(Float, default=0.0)
    score_partants: Mapped[float] = mapped_column(Float, default=0.0)
    score_hippodrome: Mapped[float] = mapped_column(Float, default=0.0)
    score_poids: Mapped[float] = mapped_column(Float, default=0.0)
    # F3 : critères spécifiques trot
    score_corde: Mapped[float] = mapped_column(Float, default=50.0)
    score_regularite: Mapped[float] = mapped_column(Float, default=50.0)
    score_recence: Mapped[float] = mapped_column(Float, default=50.0)
    is_value_bet: Mapped[bool] = mapped_column(Boolean, default=False)
    confiance: Mapped[str] = mapped_column(String(10), default="LOW")  # HIGH / MEDIUM / LOW
    explication: Mapped[str] = mapped_column(Text, default="")
    # F4 : outsider signals
    driver_change: Mapped[bool] = mapped_column(Boolean, default=False)
    score_outsider: Mapped[float] = mapped_column(Float, default=0.0)
    # F1 : position d'arrivée
    position_arrivee: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # F5 : double scoring (Expert vs Auto-calibré)
    score_global_expert: Mapped[float] = mapped_column(Float, default=0.0)
    score_global_auto: Mapped[float] = mapped_column(Float, default=0.0)
    # F6 : score sans cote (indépendant de la cote bookmaker)
    score_sans_cote: Mapped[float] = mapped_column(Float, default=0.0)
    # Scores gains et age (stockés pour calibration)
    score_gains: Mapped[float] = mapped_column(Float, default=50.0)
    score_age: Mapped[float] = mapped_column(Float, default=50.0)

    course: Mapped["Course"] = relationship("Course", back_populates="participants")


class Bet(Base):
    """Pari persisté en base (remplace localStorage)."""
    __tablename__ = "bets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # type : GAGNANT | PLACE | COUPLE | TIERCE | DEUX_SUR_QUATRE
    type_pari: Mapped[str] = mapped_column(String(20), default="GAGNANT")
    montant: Mapped[float] = mapped_column(Float, default=2.0)
    # statut : EN_ATTENTE | GAGNE | PERDU
    statut: Mapped[str] = mapped_column(String(15), default="EN_ATTENTE")
    gain_reel: Mapped[float | None] = mapped_column(Float, nullable=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    course_label: Mapped[str] = mapped_column(String(200), default="")
    hippodrome: Mapped[str] = mapped_column(String(100), default="")
    # JSON list de {numero, nom, cote}
    chevaux_json: Mapped[str] = mapped_column(Text, default="[]")

    course: Mapped["Course | None"] = relationship("Course", back_populates="bets")


class ScoringWeight(Base):
    """Poids du moteur de scoring, appris sur l'historique, par discipline."""
    __tablename__ = "scoring_weights"
    __table_args__ = (
        UniqueConstraint("discipline", "critere", name="uq_scoring_weight_disc_critere"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discipline: Mapped[str] = mapped_column(String(20), default="PLAT", index=True)  # PLAT | TROT_ATTELE | TROT_MONTE | HAIE | STEEPLE | CROSS
    critere: Mapped[str] = mapped_column(String(50), index=True)
    poids: Mapped[float] = mapped_column(Float, default=0.0)
    precision: Mapped[float] = mapped_column(Float, default=0.0)
    nb_samples: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CalibrationWeight(Base):
    """Poids auto-calibrés depuis l'historique, par discipline et critère."""
    __tablename__ = "calibration_weights"
    __table_args__ = (
        UniqueConstraint("discipline", "critere", name="uq_calibration_weight_disc_critere"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discipline: Mapped[str] = mapped_column(String(20), default="PLAT", index=True)
    critere: Mapped[str] = mapped_column(String(50), index=True)
    poids: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class DailyStats(Base):
    __tablename__ = "daily_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(10), index=True, unique=True)  # YYYY-MM-DD
    nb_courses: Mapped[int] = mapped_column(Integer, default=0)
    nb_value_bets: Mapped[int] = mapped_column(Integer, default=0)
    nb_top_picks_correct: Mapped[int] = mapped_column(Integer, default=0)
    nb_courses_finished: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
