"""Section 2 red-flag gate. Bypasses normal chat when Plan B is required."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from extract_clinical_data import extract_all

PLAN_B_PATH = Path(__file__).resolve().parent / "clinical_data" / "plan_b.json"
PROTECTED_FRAGMENTS = [
    "112",
    "061",
    "024",
    "900 925 555",
    "900 70 30 30",
    "900 900 120",
    "CUESB",
    "CatSalut",
    "Hospital del Mar",
    "Hospital Clínic",
    "Sant Pau",
    "Vall d'Hebron",
    "Carrer de la Llacuna, 25",
    "Poblenou",
    "Centre d'Urgències i Emergències Socials",
]

CATEGORY_TO_SCENARIO = {
    "riesgo_vital_ideacion_suicida": "A",
    "conductas_autolesivas": "A",
    "descompensacion_panico_incontrolable": "A",
    "desconexion_realidad_psicosis": "A",
    "riesgo_terceros": "A",
    "vulnerabilidad_abuso_activo": "C",
    "intoxicacion_aguda": "A",
    "crisis_supervivencia_desamparo": "B",
    "resistencia_institucional_papeles": "D",
}

KEYWORD_FALLBACK = {
    "A": [
        r"suicid",
        r"self[- ]harm",
        r"hurt myself",
        r"harm myself",
        r"end my life",
        r"end it all",
        r"hacerme da[ñn]o",
        r"lastimarme",
        r"quitarme la vida",
        r"quiero morir",
        r"want to die",
        r"kill myself",
        r"me quiero matar",
        r"mejor muerto",
        r"no vale la pena seguir",
        r"autolesi",
        r"me corto",
        r"me voy a cortar",
        r"cut myself",
        r"self[- ]harm",
        r"escucho voces",
        r"hearing voices",
        r"me persiguen",
        r"voy a matar",
        r"kill (him|her|them)",
        r"estoy muy drogado",
        r"he bebido demasiado",
        r"overdose",
    ],
    "B": [
        r"me qued[eé] en la calle",
        r"no tengo d[oó]nde dormir",
        r"me (acaban de )?echar(on)?",
        r"kicked out of my room",
        r"homeless",
        r"nowhere to sleep",
        r"sleep on the street",
        r"sans abri",
        r"senza tetto",
    ],
    "C": [
        r"violencia de g[eé]nero",
        r"me est[aá] pegando",
        r"me agredi[oó]",
        r"abuso sexual",
        r"domestic violence",
        r"he is hitting me",
        r"violence conjugale",
        r"violenza domestica",
        r"me tiene encerrad",
    ],
}

INSTITUTIONAL_FEAR = [
    r"no tengo papeles",
    r"sin papeles",
    r"irregular",
    r"deport",
    r"extranjer[ií]a",
    r"me van a denunciar",
    r"miedo a llamar",
    r"no puedo llamar",
    r"no papers",
    r"don'?t have papers",
    r"undocumented",
    r"immigration",
    r"sans papiers",
    r"senza documenti",
]

GROUNDING_COMPLIANCE_HINTS = [
    r"\b(listo|ya est[oá]y|ya lo hice|hecho|estoy aqu[ií]|estoy ah[ií]|preparad[oa])\b",
    r"\b(ready|done|i'?m here|i'?m there|did it|okay|ok)\b",
    r"\b(ba[ñn]o|cocina|agua fr[ií]a|grifo|hielo|cara fr[ií]a|pared|suelo|pies|clav[ií]cula|respir)\b",
    r"\b(bathroom|kitchen|cold water|tap|ice|wall|floor|barefoot|breathing|collarbone)\b",
]

CRISIS_ESCALATION_HINTS = [
    r"suicid",
    r"morir",
    r"matar",
    r"cortar",
    r"sangre",
    r"pastillas",
    r"saltar",
    r"ventana",
    r"infarto",
    r"me muero",
    r"no funciona",
    r"estoy peor",
    r"perdiendo el control",
    r"losing control",
    r"getting worse",
    r"not working",
    r"dying",
    r"hurt myself",
    r"cut myself",
    r"kill myself",
    r"want to die",
]

english_hits = len(
        re.findall(
            r"\b(i|my|me|the|and|can|cannot|don|help|afraid|scared|papers|feel|chest|hurts|hurt|myself|want|nothing|tonight|anymore|tight|breathe|breath|panicking|panic|what|where|how|ready|done)\b",
            lowered,
        )
    )

def clean_spacing(text: str) -> str:
    if not text:
        return text
    cleaned = re.sub(r",(?=[A-Za-zÁÉÍÓÚÜÑáéíóúüñ])", ", ", text)
    cleaned = re.sub(r"(\d)\(([A-Za-zÁÉÍÓÚÜÑáéíóúüñ])", r"\1 (\2", cleaned)
    return cleaned


def load_plan_b() -> dict:
    extract_all(force=False)
    data = json.loads(PLAN_B_PATH.read_text(encoding="utf-8"))
    for sc in data.get("scenarios", {}).values():
        if "message" in sc:
            sc["message"] = clean_spacing(sc["message"])
    return data


def detect_user_language(text: str, fallback: str = "es") -> str:
    lowered = (text or "").lower()
    catalan_hits = len(
        re.findall(
            r"\b(estic|tinc|amb|per[oò]|qu[eè]|puc|vull|aix[oò]|molt|barri|empadronament)\b",
            lowered,
        )
    )
    italian_hits = len(
        re.findall(
            r"\b(ciao|non|sono|perch[eé]|aiuto|mi|sento|petto|respiro|grazie|vorrei|paura)\b",
            lowered,
        )
    )
    french_hits = len(
        re.findall(
            r"\b(je|j'ai|pas|aide|peur|suis|bonjour|poitrine|respirer|merci|dans|avec)\b",
            lowered,
        )
    )
    english_hits = len(
        re.findall(
            r"\b(i|my|me|the|and|can|cannot|don|help|afraid|scared|papers|feel|chest|hurts|tight|breathe|breath|panicking|panic|what|where|how|ready|done)\b",
            lowered,
        )
    )
    spanish_hits = len(
        re.findall(
            r"\b(que|qu[eé]|estoy|tengo|me|mi|el|la|en|con|ayuda|miedo|papeles|pecho|aire|angustia|ba[ñn]o|hola|soy)\b",
            lowered,
        )
    )
    scores = {
        "ca": catalan_hits,
        "it": italian_hits,
        "fr": french_hits,
        "en": english_hits,
        "es": spanish_hits,
    }
    winner = max(scores, key=scores.get)
    if scores[winner] == 0:
        return fallback if fallback in scores else "es"
    return winner


def _keyword_scenario(text: str) -> str | None:
    for scenario, patterns in KEYWORD_FALLBACK.items():
        for pattern in patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return scenario
    return None


def _fear_of_calling(text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in INSTITUTIONAL_FEAR)


def _is_grounding_compliance(text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in GROUNDING_COMPLIANCE_HINTS)


def _has_crisis_escalation(text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in CRISIS_ESCALATION_HINTS)


def recent_red_flag(profile: dict) -> bool:
    last = (profile or {}).get("last_red_flag") or {}
    when = last.get("at")
    scenario = last.get("scenario")
    if not when or scenario not in {"A", "B", "C"}:
        return False
    try:
        stamped = datetime.fromisoformat(when)
    except ValueError:
        return False
    return datetime.now() - stamped <= timedelta(hours=12)


async def classify_red_flag(
    client,
    user_message: str,
    profile: dict,
    recent_turns: list | None = None,
    active_ficha: dict | None = None,
) -> dict:
    """Return {triggered, category, scenario, reason}."""
    after_flag = recent_red_flag(profile)
    fallback_scenario = _keyword_scenario(user_message)

    if after_flag and _fear_of_calling(user_message):
        return {
            "triggered": True,
            "category": "resistencia_institucional_papeles",
            "scenario": "D",
            "reason": "User fears calling after a red flag (papers / irregular status).",
        }
    if fallback_scenario:
        category = next(
            (k for k, v in CATEGORY_TO_SCENARIO.items() if v == fallback_scenario),
            "keyword_match",
        )
        return {
            "triggered": True,
            "category": category,
            "scenario": fallback_scenario,
            "reason": "Keyword fallback matched a Section 2 indicator.",
        }

    # Prevent false positives when user is following an active clinical grounding Ficha
    if (
        active_ficha
        and _is_grounding_compliance(user_message)
        and not _has_crisis_escalation(user_message)
    ):
        return {
            "triggered": False,
            "category": None,
            "scenario": None,
            "reason": "User is following active grounding Ficha instructions.",
        }

    system = """You are a clinical safety classifier for Nouniu in Barcelona.
Decide if the user message matches ANY of these 8 red-flag categories (explicit OR implicit):
1. riesgo_vital_ideacion_suicida (wish to die, goodbye messages, suicide plan)
2. conductas_autolesivas (active self-harm OR explicit urge/intent to hurt, cut, or burn oneself)
3. descompensacion_panico_incontrolable (communication completely broken; feels dying/heart attack; grounding exercise ALREADY tried and explicitly failing/escalating out of control)
4. desconexion_realidad_psicosis (hallucinations, severe paranoia, persistent incoherent speech)
5. riesgo_terceros (threats to hurt others)
6. vulnerabilidad_abuso_activo (gender violence, assault, captivity happening now)
7. intoxicacion_aguda (too drunk/high to be contained verbally right now)
8. crisis_supervivencia_desamparo (just lost housing, nowhere to sleep TONIGHT)

If RED_FLAG_JUST_TRIGGERED=True and the user now fears calling due to lacking papers / deportation / police, output resistencia_institucional_papeles -> D.

CRITICAL ANTI-FALSE-POSITIVE RULES:
- If ACTIVE_GROUNDING_EXERCISE is present and the user is confirming or following Nouniu's instructions (e.g. going to the bathroom or kitchen, turning on cold water, holding ice until cold stings, pushing a wall, barefoot grounding, breathing, or reporting body temperature/sensations requested by the exercise), NEVER trigger conductas_autolesivas or descompensacion_panico_incontrolable.
- Moderate sadness, loneliness, caregiver exhaustion, or communicative anxiety symptoms (chest tightness, shortness of breath, crying, racing heart) are NOT red flags—those are handled by clinical Fichas.

Return JSON only: {"triggered": bool, "category": string|null, "scenario": "A"|"B"|"C"|"D"|null, "reason": string}
"""
    context_lines = [f"RED_FLAG_JUST_TRIGGERED={after_flag}"]
    if active_ficha:
        context_lines.append(
            f"ACTIVE_GROUNDING_EXERCISE={active_ficha.get('title')} | "
            f"LAST_INSTRUCTION_SENT={active_ficha.get('step_text', '')}"
        )
    if recent_turns:
        formatted_turns = "\n".join(
            f"{t.get('role', 'user')}: {t.get('content', '')}" for t in recent_turns[-3:]
        )
        context_lines.append(f"RECENT_CONVERSATION:\n{formatted_turns}")
    context_lines.append(f"USER_MESSAGE:\n{user_message}")

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": "\n\n".join(context_lines)},
            ],
            response_format={"type": "json_object"},
            max_tokens=200,
            temperature=0,
        )
        data = json.loads(response.choices[0].message.content)
        scenario = data.get("scenario")
        triggered = bool(data.get("triggered")) and scenario in {"A", "B", "C", "D"}
        if scenario == "D" and not after_flag:
            triggered = False
            scenario = None
        if (
            triggered
            and active_ficha
            and data.get("category") == "conductas_autolesivas"
            and not _has_crisis_escalation(user_message)
        ):
            triggered = False
            scenario = None
        return {
            "triggered": triggered,
            "category": data.get("category") if triggered else None,
            "scenario": scenario if triggered else None,
            "reason": data.get("reason", ""),
        }
    except Exception as exc:
        print(f"[SAFETY CHECK] classifier error: {exc}")
        return {
            "triggered": False,
            "category": None,
            "scenario": None,
            "reason": "classifier_error",
        }


async def translate_plan_b(client, message: str, language: str) -> str:
    message = clean_spacing(message)
    if language not in {"en", "fr", "it", "ca"}:
        return message
    names = {"en": "English", "fr": "French", "it": "Italian", "ca": "Catalan"}
    prompt = (
        f"Translate this crisis referral message faithfully into {names[language]}. "
        "Keep EVERY Barcelona phone number, hospital name, CUESB name, address, "
        "and Catalan proper noun EXACTLY unchanged. Do not add advice. "
        "Keep clear spacing and short paragraphs suitable for WhatsApp."
    )
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": message},
            ],
            max_tokens=550,
            temperature=0,
        )
        translated = clean_spacing(response.choices[0].message.content.strip())
        for fragment in PROTECTED_FRAGMENTS:
            if fragment not in translated and fragment in message:
                translated = f"{translated}\n{fragment}"
        return translated
    except Exception as exc:
        print(f"[SAFETY CHECK] translation error: {exc}")
        return message


async def run_safety_gate(
    client,
    user_message: str,
    profile: dict,
    recent_turns: list | None = None,
    active_ficha: dict | None = None,
) -> dict:
    fallback_lang = (profile or {}).get("last_language") or "es"
    language = detect_user_language(user_message, fallback=fallback_lang)
    result = await classify_red_flag(
        client,
        user_message,
        profile,
        recent_turns=recent_turns,
        active_ficha=active_ficha,
    )
    print(
        f"[SAFETY CHECK] triggered={result['triggered']} "
        f"category={result.get('category')} scenario={result.get('scenario')} "
        f"lang={language}"
    )
    if not result["triggered"]:
        return {**result, "output_message": None, "language": language}

    plan = load_plan_b()
    scenario_id = result["scenario"]
    raw = plan["scenarios"][scenario_id]["message"]
    output = await translate_plan_b(client, raw, language)
    result["output_message"] = output
    result["language"] = language
    return result