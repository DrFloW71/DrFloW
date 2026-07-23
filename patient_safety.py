from __future__ import annotations

from dataclasses import dataclass


PATIENT_SAFETY_OK = "ok"
PATIENT_SAFETY_WARNING = "warning"
PATIENT_SAFETY_BLOCKED = "blocked"


@dataclass(frozen=True)
class PatientSafetyState:
    level: str
    title: str
    detail: str

    @property
    def allows_generation(self) -> bool:
        return self.level != PATIENT_SAFETY_BLOCKED

    @property
    def allows_import(self) -> bool:
        return self.level == PATIENT_SAFETY_OK


def normalize_patient_id(value: object) -> str:
    return str(value or "").strip().split("|", 1)[0].strip()


def evaluate_patient_context(
    context,
    *,
    require_patient_id: bool = False,
) -> PatientSafetyState:
    if context is None:
        return PatientSafetyState(
            PATIENT_SAFETY_BLOCKED,
            "Aucun dossier WEDA verrouillé",
            "Récupère le contexte du patient avant d’utiliser WEDA.",
        )

    patient_id = normalize_patient_id(getattr(context, "patient_id", ""))
    identity = str(
        getattr(context, "patient_identity", "")
        or getattr(context, "patient_name", "")
        or patient_id
        or "patient reçu"
    ).strip()
    if not patient_id:
        level = PATIENT_SAFETY_BLOCKED if require_patient_id else PATIENT_SAFETY_WARNING
        return PatientSafetyState(
            level,
            f"Identifiant WEDA absent — {identity}",
            "Le contexte reste utilisable, mais le PatDk manque : import WEDA verrouillé.",
        )
    return PatientSafetyState(
        PATIENT_SAFETY_OK,
        f"Dossier verrouillé — {identity}",
        "Contexte valide sans expiration • PatDk vérifié",
    )


def patient_ids_match(left: object, right: object) -> bool:
    normalized_left = normalize_patient_id(left)
    normalized_right = normalize_patient_id(right)
    return bool(normalized_left and normalized_right and normalized_left == normalized_right)
