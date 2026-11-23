"""Section 1 clinical voice + Ficha bank + per-phone session state."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from extract_clinical_data import extract_all
from safety_gate import clean_spacing, detect_user_language, run_safety_gate

FICHAS_PATH = Path(__file__).resolve().parent / "clinical_data" / "fichas.json"

SOFT_CLOSE_AFTER_FICHA = (
    "Qué bueno sentirte un poco más en calma. Si lo que necesitas ahora es "
    "desconectar y descansar, está perfecto. Recuerda que si más adelante te da "
    "curiosidad entender por qué el cuerpo reacciona así, aquí voy a estar para explicártelo."
)
RADICAL_ACCEPTANCE = (
    "Lo entiendo. A veces el cuerpo está tan agotado que intentar sentirse mejor "
    "es un enorme esfuerzo. No tienes que hacer nada. Me quedo por aquí acompañándote."
)
ANTI_INFINITY_BYE = (
    "Descansa mucho. Mañana será otro día y aquí estaré si me necesitas. Un abrazo."
)

ACUTE_PATTERNS = [
    r"dolor(?:es)? (?:en )?el pecho",
    r"me duele (?:mucho )?el pecho",
    r"(?:opresi[oó]n|presi[oó]n) en el pecho",
    r"coraz[oó]n (?:muy )?(?:a mil|acelerado|r[aá]pido|latiendo)",
    r"pecho cerrado",
    r"me falta el aire",
    r"se me va el aire",
    r"no puedo respirar",
    r"ahogo",
    r"me ahogo",
    r"taquicardia",
    r"ataque de p[aá]nico",
    r"crisis de angustia",
    r"llanto (?:descontrolado|incontrolable)",
    r"no paro de llorar",
    r"chest (?:pain|hurts|tight|tightness|feels tight|ache|pressure)",
    r"my chest hurts",
    r"can'?t (?:breathe|catch my breath)",
    r"cannot (?:breathe|catch my breath)",
    r"shortness of breath",
    r"hard to breathe",
    r"panic(?:king| attack)",
    r"heart (?:is )?(?:racing|pounding)",
    r"hyperventilat",
    r"crying uncontrollably",
    r"crise de panique",
    r"mal [aà] la poitrine",
    r"arrive pas [aà] respirer",
    r"attacco di panico",
    r"manca il respiro",
    r"non riesco a respirare",
    r"dolore al petto",
    r"no puc respirar",
    r"em fa mal el pit",
    r"atac de p[aà]nic",
]

EVENT_PATTERNS = [
    r"eventos?",
    r"fiesta",
    r"club",
    r"conocer gente",
    r"actividades",
    r"planes",
    r"what('?s| is) on",
    r"plans? (in|en) barcelona",
    r"community",
    r"meet people",
    r"free activities",
]

ADMIN_PATTERNS = [
    r"empadron",
    r"\bnie\b",
    r"\bcue\b",
    r"\btie\b",
    r"padr[oó]n",
    r"alquiler",
    r"piso",
    r"trabajo",
    r"\bjob\b",
    r"housing",
    r"catal[aá]n",
    r"idioma",
    r"language",
    r"metro",
    r"catsalut",
    r"\bcap\b",
    r"ajuntament",
    r"cita extranjer",
    r"tr[aá]mite",
]

COMORBIDITY_PATTERNS = [
    r"\btea\b",
    r"autis",
    r"espectro autista",
    r"\btlp\b",
    r"lim[ií]trofe",
    r"borderline",
    r"\btdah\b",
    r"\badhd\b",
    r"bipolar",
    r"\btoc\b",
]

MEANING_OR_PHASE2_PATTERNS = [
    r"por qu[eé] me siento as[ií]",
    r"why do i feel (?:like this|this way)",
    r"me rechazaron el empadronamiento",
    r"me denegaron",
]

GOODBYE_PATTERNS = [
    r"\bdescanso\b",
    r"deja(rlo|lo) (hasta )?aqu[ií]",
    r"hasta luego",
    r"adi[oó]s",
    r"bye\b",
    r"good ?night",
    r"buenas noches",
    r"no quiero (hacer )?nada",
    r"prefiero descansar",
]

ACCEPT_FICHA_PATTERNS = [
    r"\bs[ií]\b",
    r"\bok\b",
    r"\bokay\b",
    r"\bvale\b",
    r"\bvamos\b",
    r"\bhazlo\b",
    r"\byes\b",
    r"\bsure\b",
    r"\bokey\b",
    r"de acuerdo",
    r"pro[bv]emos",
    r"ejercicio",
    r"herramienta",
    r"me animo",
]


def load_fichas() -> dict:
    extract_all(force=False)
    data = json.loads(FICHAS_PATH.read_text(encoding="utf-8"))
    out = {}
    for f in data["fichas"]:
        for k in ("step_1", "step_2", "step_3", "title", "cuando_usarla"):
            if k in f and isinstance(f[k], str):
                f[k] = clean_spacing(f[k])
        out[int(f["id"])] = f
    return out


def default_clinical_state() -> dict:
    return {
        "name": None,
        "pronouns": None,
        "origin": None,
        "arrival_date": None,
        "context": None,
        "family_network": None,
        "pain_point": None,
        "upcoming_events": None,
        "pap_date": None,
        "pap_questions": 0,
        "pap_phase2_done": False,
        "pap_cycle_done": False,
        "pending_ficha_id": None,
        "active_ficha_id": None,
        "active_ficha_step_text": None,
        "ficha_next_step": None,
        "last_red_flag": None,
        "last_mode": None,
        "last_language": "es",
    }


def merge_profile(raw_profile) -> dict:
    state = default_clinical_state()
    if not raw_profile:
        return state
    if isinstance(raw_profile, str):
        try:
            raw_profile = json.loads(raw_profile)
        except json.JSONDecodeError:
            return state
    if isinstance(raw_profile, dict):
        state.update({k: v for k, v in raw_profile.items() if v is not None})
    return state


def reset_pap_if_new_day(state: dict) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    if state.get("pap_date") != today:
        state["pap_date"] = today
        state["pap_questions"] = 0
        state["pap_phase2_done"] = False
        state["pap_cycle_done"] = False


def has_acute_physical(text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in ACUTE_PATTERNS)


def has_event_topic(text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in EVENT_PATTERNS)


def has_admin_topic(text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in ADMIN_PATTERNS)


def looks_practical(text: str) -> bool:
    if any(re.search(p, text, flags=re.IGNORECASE) for p in MEANING_OR_PHASE2_PATTERNS):
        return False
    return has_event_topic(text) or has_admin_topic(text)


def has_comorbidity(text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in COMORBIDITY_PATTERNS)


def has_meaning_or_direct_phase2(text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in MEANING_OR_PHASE2_PATTERNS)


def looks_goodbye(text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in GOODBYE_PATTERNS)


def looks_accept(text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in ACCEPT_FICHA_PATTERNS)


def memory_block(state: dict) -> str:
    bits = []
    for key, label in [
        ("name", "Nombre"),
        ("pronouns", "Pronombres"),
        ("origin", "Origen"),
        ("arrival_date", "Fecha de llegada a Barcelona"),
        ("context", "Contexto actual"),
        ("family_network", "Red afectiva / mascotas / familia"),
        ("pain_point", "Punto de dolor dinámico"),
        ("upcoming_events", "Eventos próximos"),
    ]:
        if state.get(key):
            bits.append(f"- {label}: {state[key]}")
    if not bits:
        return "Todavía no hay memoria emocional guardada."
    return "\n".join(bits)


SYSTEM_PROMPT = """Eres Nouniu ("Nuevo Nido" en catalán): compañero de IA diseñado para guiar y sostener a las personas que migran y se establecen en Barcelona, Cataluña.
Tu misión es holística: orientación práctica/logística, integración sociocultural, contención psicológica (duelo migratorio, PAP, regulación emocional) y transparencia compasiva. Eres un puente temporal, no el destino: tu éxito es ayudar a la persona a conectarse con el mundo real de Barcelona.

VOZ CLÍNICA Y LÍMITES DE LENGUAJE
- Cálido, acogedor, empático y validante, manteniendo distancia terapéutica profesional. Cero paternalismo ("pobrecito"), no infantilices ni des consejos directivos de vida.
- Mirroring clínico: mensajes cortos y angustiados → respuestas breves y ancladas al presente; mensajes largos y reflexivos → respuestas un poco más desarrolladas.
- Perspectiva de género, diversidad y derechos humanos (enfoque afirmativo LGBTQIA+, reconociendo vulnerabilidades interseccionales como realidades estructurales del sistema, nunca debilidades personales).
- ESTRICTAMENTE PROHIBIDO usar jerga clínica con el usuario ("psicoeducación", "grounding", "triage", "fase 1").
- ESTRICTAMENTE PROHIBIDO usar frases robóticas o vacías como "Como inteligencia artificial...", "Entiendo cómo te sientes" o "Entiendo que te sientas así". Usa validadores orgánicos ("Te leo y percibo...", "Escucho lo pesado que...", "Uf, claro...", "Tiene todo el sentido...").
- Cero positivismo tóxico ("todo va a estar bien", "échale ganas", "tienes que ser fuerte").
- Prohibido diagnosticar o patologizar.
- Alucinación cero en burocracia: orienta únicamente hacia canales oficiales verificados (Ajuntament de Barcelona / 010 / Generalitat / CatSalut) o lo provisto en CURRENT LOCAL DATA. Nunca inventes requisitos, webs ni eventos.
- Transferencia hostil: si el usuario se frustra contigo o dice que eres un robot inútil, valida la rabia sin ponerte a la defensiva.
- Regla Anti-Ensayo: máximo 2-3 párrafos cortos y fáciles de digerir en WhatsApp. ESTRICTAMENTE UNA SOLA pregunta abierta al final del mensaje (o cero si es cierre). Prohibido hacer dos preguntas en el mismo mensaje.

MEMORIA EMOCIONAL (Uso sutil y natural)
- Teje lo que ya sabes del usuario (país de origen, cuánto lleva en Barcelona, mascotas o seres queridos) con naturalidad para empatizar, sin sonar como una base de datos ni fingir cuerpo humano ("pensé en ti anoche").
- Ejemplo correcto: "Sé que estos días aquí en Barcelona pueden hacer que extrañes mucho más salir a caminar con Toby por tu barrio en Chile..."

FLUJO PAP (Invisible para el usuario - Prohibido el solucionismo prematuro)
- Fase 1 (Acogida y Escucha Activa): Reflejo en espejo + Validación profunda + 1 pregunta suave sobre cómo vive esa emoción en su día a día. PROHIBIDO en Fase 1 hacer preguntas de coaching/solución ("¿Qué has intentado hasta ahora?", "¿Has considerado unirte a un grupo?").
- Fase 2 (Consolidación y Bifurcación): Normaliza el malestar como respuesta sana del duelo migratorio + si hay insomnio/rumiación/ansiedad suma en 1 sola oración un hábito básico de higiene de vida (pantallas, rutinas) + ofrece opciones en lenguaje coloquial (conversar sobre por qué la mente/cuerpo reacciona así al migrar, probar juntos un ejercicio cortito ahora mismo, o revisar recursos/actividades prácticas de Barcelona).

FICHA BASE 0: COMORBILIDADES Y FUERA DE FOCO (Filtro DSM)
1. Reconocimiento sin tratamiento (TEA, TLP, TDAH, Depresión previa, etc.): ESTRICTAMENTE PROHIBIDO dar pautas para tratar o curar el trastorno central o tocar medicación. Aplica el LENTE MIGRATORIO para validar cómo migrar duplica la carga y ofrece contención breve al usuario hoy + derivación profesional humana.
   - Ejemplo TEA: "El cambio de país rompe todas las rutinas y la predictibilidad, que son vitales para un niño en el espectro. Es completamente lógico que él esté desregulado y que tú estés al borde del colapso por sostenerlo. Tu carga es doble. Para abordar pautas específicas del TEA es importante apoyarte en un especialista aquí (a través de tu CAP/CSMIJ), pero hoy quiero cuidarte a ti: ¿te gustaría que hagamos un ejercicio breve para que tú puedas respirar 5 minutos?"
   - Ejemplo TLP: "Las personas con TLP sienten las emociones con muchísima intensidad. Sumar a eso el estrés brutal de no tener tu red de apoyo en Barcelona es una carga enorme. Vamos a usar herramientas de contención física para acompañarte hoy, y es vital que conectes con un profesional aquí lo antes posible."
2. Fuera de foco no migratorio (trauma infantil, trastornos sexuales, TCA severo): valida el dolor, aclara con calidez que tu especialidad es exclusivamente la adaptación y el duelo migratorio, deriva a un psicólogo humano especialista y ofrece regular la ansiedad general del momento.

EJEMPLOS DE ORO
- Categoría A (Soledad - Fase 1): "Escucho lo pesado que se hacen los días y lo doloroso que es sentirte invisible. Es una sensación de soledad muy profunda y es completamente válido que te sientas así. Construir una red desde cero desgasta muchísimo... ¿Sientes que hay algún momento específico del día o de la semana donde esta sensación se hace más fuerte?"
- Categoría C (Frustración burocrática - Fase 2): "Comprendo perfectamente la rabia y el agotamiento tras recibir ese rechazo. Chocar contra la burocracia genera una impotencia enorme y es natural que te den ganas de rendirte. Tómate el tiempo que necesites para soltar ese enojo. Cuando te sientas con más energía, si quieres, te puedo indicar las vías oficiales del Ajuntament para revisar ese trámite, o enseñarte una técnica breve para descargar esa frustración del cuerpo. ¿Qué necesitas en este momento?"

IDIOMA: Responde siempre en el idioma del último mensaje del usuario (español, inglés, francés, italiano o catalán).
"""


def ficha_catalog_for_prompt(fichas: dict) -> str:
    lines = []
    for i in range(1, 39):
        f = fichas[i]
        lines.append(f"{i}. {f['title']} — {f['cuando_usarla']}")
    return "\n".join(lines)


async def extract_memory(client, user_message: str, state: dict) -> None:
    prompt = """Extract ONLY facts the user explicitly stated in this message. Return JSON:
{"name": null, "pronouns": null, "origin": null, "arrival_date": null, "context": null, "family_network": null, "pain_point": null, "upcoming_events": null}
Include pets (e.g. "perro Toby") or children/partner in family_network. Leave null if not mentioned. Do not invent."""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            max_tokens=220,
            temperature=0,
        )
        data = json.loads(response.choices[0].message.content)
        for key in [
            "name",
            "pronouns",
            "origin",
            "arrival_date",
            "context",
            "family_network",
            "pain_point",
            "upcoming_events",
        ]:
            value = data.get(key)
            if value:
                state[key] = value
    except Exception as exc:
        print(f"[MODE] memory extract skipped: {exc}")


async def choose_ficha(client, user_message: str, fichas: dict, prefer_calming: bool) -> int:
    lowered = user_message.lower()
    if prefer_calming:
        if any(
            w in lowered
            for w in [
                "pecho",
                "chest",
                "poitrine",
                "petto",
                "pit",
                "aire",
                "breath",
                "respir",
                "pánico",
                "panico",
                "panic",
                "ahogo",
            ]
        ):
            return 1
        return 9
    if has_comorbidity(user_message):
        return 24
    catalog = ficha_catalog_for_prompt(fichas)
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Pick ONE ficha id (1-38) that best fits the user's need. "
                        "JSON: {\"id\": number}. Prefer calming somatic fichas 1-9 for panic/body, "
                        "24 for exhausted caregivers. "
                        f"Catalog:\n{catalog}"
                    ),
                },
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            max_tokens=50,
            temperature=0,
        )
        chosen = int(json.loads(response.choices[0].message.content).get("id", 8))
        if 1 <= chosen <= 38:
            return chosen
    except Exception as exc:
        print(f"[FICHA STEP] chooser error: {exc}")
    return 8


async def translate_clinical_text(client, text: str, language: str) -> str:
    text = clean_spacing(text)
    if language not in {"en", "fr", "it", "ca"}:
        return text
    names = {"en": "English", "fr": "French", "it": "Italian", "ca": "Catalan"}
    prompt = (
        f"Translate this warm clinical guidance message faithfully into natural {names[language]}. "
        "Preserve the exact calming, grounded, non-clinical tone and direct step instruction. "
        "Keep Barcelona institution names (CAP, CatSalut, Ajuntament, CUESB) unchanged. "
        "Do not add extra steps, headers, or disclaimers."
    )
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
            max_tokens=450,
            temperature=0.1,
        )
        return clean_spacing(response.choices[0].message.content.strip())
    except Exception as exc:
        print(f"[FICHA STEP] translation error: {exc}")
        return text


async def maybe_translate(client, text: str, language: str) -> str:
    return await translate_clinical_text(client, text, language)


async def emit_ficha_step(client, state: dict, fichas: dict, language: str, step: int) -> str:
    ficha_id = state["active_ficha_id"]
    ficha = fichas[ficha_id]
    key = f"step_{step}"
    raw_step = ficha[key]
    state["active_ficha_step_text"] = raw_step

    if step == 3:
        body_es = f"{raw_step}\n\n{SOFT_CLOSE_AFTER_FICHA}"
        state["active_ficha_id"] = None
        state["active_ficha_step_text"] = None
        state["ficha_next_step"] = None
        state["pap_phase2_done"] = True
        state["pap_cycle_done"] = True
        print(f"[FICHA STEP] ficha={ficha_id} title={ficha['title']} step={step}")
        return await translate_clinical_text(client, body_es, language)

    state["ficha_next_step"] = step + 1
    print(f"[FICHA STEP] ficha={ficha_id} title={ficha['title']} step={step}")
    return await translate_clinical_text(client, raw_step, language)


def _format_pinecone_match(match: dict) -> str:
    meta = match.get("metadata") or {}
    parts = []
    for key in (
        "titulo",
        "title",
        "nombre",
        "categoria",
        "tipo",
        "texto",
        "text",
        "descripcion",
        "fecha",
        "lugar",
        "direccion",
        "url",
        "link",
    ):
        val = meta.get(key)
        if val:
            parts.append(f"{key}: {val}")
    if not parts and meta:
        parts = [f"{k}: {v}" for k, v in meta.items() if v]
    return " | ".join(parts)


async def retrieve_barcelona(openai_client, pinecone_index, user_message: str) -> str:
    try:
        queries = []
        if has_event_topic(user_message) and has_admin_topic(user_message):
            queries.append((f"{user_message} eventos actividades gratis conocer gente Barcelona", 4))
            queries.append((f"{user_message} trámites oficiales empadronamiento NIE CAP Ajuntament Barcelona", 4))
        elif has_event_topic(user_message):
            queries.append((f"{user_message} eventos actividades culturales comunidad Barcelona", 5))
        else:
            queries.append((f"{user_message} trámites recursos oficiales Barcelona Ajuntament Generalitat", 5))

        seen_ids = set()
        formatted_items = []
        for q_text, k in queries:
            embed_response = await openai_client.embeddings.create(
                input=q_text,
                model="text-embedding-3-small",
            )
            results = pinecone_index.query(
                vector=embed_response.data[0].embedding,
                top_k=k,
                include_metadata=True,
            )
            for match in results.get("matches") or []:
                mid = match.get("id") or str(match.get("metadata"))
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
                line = _format_pinecone_match(match)
                if line:
                    formatted_items.append(f"- {line}")

        if not formatted_items:
            retrieved = "No specific matching entries found in nouniu-db."
        else:
            retrieved = "\n".join(formatted_items[:6])

        preview = retrieved.replace("\n", " ")[:140]
        print(f"[DB/RAG] used=True matches={len(formatted_items)} preview={preview}")
        return retrieved
    except Exception as exc:
        print(f"[DB/RAG] used=False error={exc}")
        return "Database offline."


async def generate_clinical_reply(
    client,
    user_message: str,
    history: list,
    state: dict,
    retrieved_info: str | None,
    language: str,
    comorbidity_turn: bool = False,
    force_phase2: bool = False,
) -> tuple[str, str]:
    """Return (reply_text, executed_stage)."""
    q_asked = state.get("pap_questions", 0)

    if comorbidity_turn:
        stage = "comorbidity"
    elif retrieved_info is not None:
        stage = "practical"
    elif state.get("pap_cycle_done"):
        stage = "maintenance"
    elif force_phase2 or (q_asked >= 3 and not state.get("pap_phase2_done")):
        stage = "phase2"
    else:
        stage = "phase1"

    extra = [
        f"Respond strictly in language code: '{language}'.",
        "Ask AT MOST ONE open question at the very end, or zero if closing.",
    ]

    if stage == "comorbidity":
        extra.append(
            "FICHA BASE 0 ACTIVE: The user mentioned a clinical diagnosis (e.g. TEA/ASD, TLP/BPD, TDAH). "
            "Do NOT give guidelines to treat the disorder itself. Explicitly apply the Migratory Lens "
            "(validate how migrating breaks vital routines/predictability or support networks: 'tu carga es doble'), "
            "kindly suggest consulting a local specialist (via CAP / CSMIJ / CSMA) for the disorder itself, "
            "and offer a brief 5-minute caregiver breathing/pause exercise together right now."
        )
    elif stage == "practical":
        extra.append(f"CURRENT LOCAL DATA FROM NOUNIU-DB:\n{retrieved_info}")
        extra.append(
            "Share concrete relevant details/links from CURRENT LOCAL DATA clearly. "
            "Format for WhatsApp: write plain raw URLs (e.g. https://www.vxl.cat), NEVER Markdown links like [Name](url). "
            "If the user also asked about an official procedure (like empadronamiento, NIE, or CAP) "
            "not detailed in CURRENT LOCAL DATA, direct them accurately to Ajuntament de Barcelona "
            "(seuelectronica.ajuntament.barcelona.cat or calling 010 / OAC offices) without inventing steps."
        )
    elif stage == "phase1":
        extra.append(
            f"CURRENT STAGE: PAP Phase 1 (Inquiry {q_asked + 1} of 3). "
            "Mirror and validate their emotional experience deeply (like Golden Example A). "
            "Subtly weave at least one detail from MEMORIA EMOCIONAL if available (e.g. country of origin, pet name, arrival time) "
            "without listing facts like a robot. "
            "STRICTLY FORBIDDEN in Phase 1: Do NOT say 'Entiendo cómo te sientes' or 'Entiendo que te sientas así'. "
            "Do NOT ask premature solution/coaching questions like '¿Qué has intentado hasta ahora?' or '¿Has considerado unirte a un grupo?'. "
            "Ask ONLY ONE gentle question exploring how or when this feeling shows up in their day."
        )
    elif stage == "phase2":
        extra.append(
            "CURRENT STAGE: PAP Phase 2 (Consolidation & Support Bifurcation). "
            "Stop probing context. 1) Normalize what they feel as a completely healthy neurological/emotional response to migratory grief. "
            "2) If sleep, rumination, or anxiety came up, add ONE brief sentence on basic life hygiene (routines/screens). "
            "3) Offer colloquial options so the user chooses the route: chatting briefly about why the mind/body reacts like this when migrating, "
            "trying a short exercise together right now to release tension, or checking local Barcelona activities/official info. "
            "End with ONE warm choice question."
        )
    else:
        extra.append(
            "CURRENT STAGE: Maintenance Active Listening (PAP cycle already completed today). "
            "Reflect and accompany warmly without starting a new clinical inquiry."
        )

    system = (
        SYSTEM_PROMPT
        + "\n\nMEMORIA EMOCIONAL DEL USUARIO (no vuelvas a preguntar lo que ya figura aquí):\n"
        + memory_block(state)
        + "\n\nINSTRUCCIONES OBLIGATORIAS DE ESTE TURNO:\n"
        + "\n".join(f"- {x}" for x in extra)
    )
    messages = [{"role": "system", "content": system}] + history[-8:]
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        max_tokens=350,
        temperature=0.45,
    )
    return clean_spacing(response.choices[0].message.content.strip()), stage


def count_new_question(reply: str) -> int:
    return 1 if "?" in reply or "¿" in reply else 0


async def handle_incoming(
    openai_client,
    pinecone_index,
    user_message: str,
    from_number: str,
    history: list,
    raw_profile,
) -> dict:
    """Full turn: safety gate first, then ficha / clinical / Barcelona RAG."""
    extract_all(force=False)
    fichas = load_fichas()
    state = merge_profile(raw_profile)
    reset_pap_if_new_day(state)

    language = detect_user_language(user_message, fallback=state.get("last_language") or "es")
    state["last_language"] = language
    await extract_memory(openai_client, user_message, state)

    active_ficha_ctx = None
    if state.get("active_ficha_id") and state["active_ficha_id"] in fichas:
        f_obj = fichas[state["active_ficha_id"]]
        active_ficha_ctx = {
            "id": state["active_ficha_id"],
            "title": f_obj["title"],
            "step_text": state.get("active_ficha_step_text") or f_obj["step_1"],
        }

    prior_turns = history[:-1] if history else []
    safety = await run_safety_gate(
        openai_client,
        user_message,
        state,
        recent_turns=prior_turns,
        active_ficha=active_ficha_ctx,
    )
    if safety["triggered"]:
        print("[MODE] safety_plan_b")
        state["last_red_flag"] = {
            "scenario": safety["scenario"],
            "at": datetime.now().isoformat(),
            "from": from_number,
        }
        state["active_ficha_id"] = None
        state["active_ficha_step_text"] = None
        state["ficha_next_step"] = None
        state["pending_ficha_id"] = None
        state["last_mode"] = "safety"
        print("[FICHA STEP] skipped because safety gate fired")
        print("[DB/RAG] used=False reason=safety_bypass")
        return {
            "output_message": safety["output_message"],
            "profile": state,
            "mode": "safety",
        }

    if looks_goodbye(user_message) and not state.get("active_ficha_id"):
        print("[MODE] closing")
        print("[FICHA STEP] none")
        print("[DB/RAG] used=False reason=user_rest")
        state["last_mode"] = "closing"
        state["pending_ficha_id"] = None
        msg = RADICAL_ACCEPTANCE if re.search(r"no quiero", user_message, re.I) else ANTI_INFINITY_BYE
        return {
            "output_message": await maybe_translate(openai_client, msg, language),
            "profile": state,
            "mode": "closing",
        }

    if state.get("active_ficha_id") and state.get("ficha_next_step") in {2, 3}:
        if looks_goodbye(user_message) or re.search(r"\bno (quiero|puedo|thanks|grazie)\b", user_message, re.I):
            print("[MODE] ficha_stopped")
            state["active_ficha_id"] = None
            state["active_ficha_step_text"] = None
            state["ficha_next_step"] = None
            print("[FICHA STEP] aborted by user")
            print("[DB/RAG] used=False")
            return {
                "output_message": await maybe_translate(openai_client, RADICAL_ACCEPTANCE, language),
                "profile": state,
                "mode": "ficha_stopped",
            }
        print("[MODE] ficha")
        print("[DB/RAG] used=False reason=ficha_in_progress")
        output = await emit_ficha_step(
            openai_client, state, fichas, language, state["ficha_next_step"]
        )
        state["last_mode"] = "ficha"
        return {"output_message": output, "profile": state, "mode": "ficha"}

    if has_acute_physical(user_message):
        ficha_id = await choose_ficha(openai_client, user_message, fichas, prefer_calming=True)
        state["active_ficha_id"] = ficha_id
        state["ficha_next_step"] = 1
        state["pending_ficha_id"] = None
        print("[MODE] acute_calming_ficha")
        print("[DB/RAG] used=False reason=acute_physical")
        output = await emit_ficha_step(openai_client, state, fichas, language, 1)
        state["last_mode"] = "ficha"
        return {"output_message": output, "profile": state, "mode": "ficha"}

    if state.get("pending_ficha_id") and looks_accept(user_message):
        state["active_ficha_id"] = state["pending_ficha_id"]
        state["pending_ficha_id"] = None
        state["ficha_next_step"] = 1
        print("[MODE] ficha")
        print("[DB/RAG] used=False reason=user_accepted_ficha")
        output = await emit_ficha_step(openai_client, state, fichas, language, 1)
        state["last_mode"] = "ficha"
        return {"output_message": output, "profile": state, "mode": "ficha"}

    comorbidity_turn = has_comorbidity(user_message)
    force_phase2 = has_meaning_or_direct_phase2(user_message)
    practical = looks_practical(user_message) and not comorbidity_turn
    retrieved = None

    if practical:
        print("[MODE] barcelona_practical")
        retrieved = await retrieve_barcelona(openai_client, pinecone_index, user_message)
    elif comorbidity_turn:
        print("[MODE] clinical_ficha_base_0")
        print("[DB/RAG] used=False reason=comorbidity_migratory_lens")
    else:
        print("[MODE] clinical_pap")
        print("[DB/RAG] used=False reason=clinical_turn")

    try:
        reply, executed_stage = await generate_clinical_reply(
            openai_client,
            user_message,
            history,
            state,
            retrieved,
            language,
            comorbidity_turn=comorbidity_turn,
            force_phase2=force_phase2,
        )
    except Exception as exc:
        print(f"⚠️ OpenAI error: {exc}")
        executed_stage = "error"
        reply = (
            "⚠️ *Technical Break*\n"
            "I am having a brief moment finding my words, but I am still here for you!\n\n"
            "While I reconnect, here are some reliable offline resources:\n"
            "📞 Emergencies: 112\n"
            "🏥 Medical Help (CatSalut): 061\n"
            "🌐 City Hall Info: 010\n\n"
            "I will be fully back online shortly. 💙"
        )

    if executed_stage == "phase1":
        asked = count_new_question(reply)
        state["pap_questions"] = min(3, state.get("pap_questions", 0) + asked)
    elif executed_stage == "phase2":
        state["pap_phase2_done"] = True
        state["pap_cycle_done"] = True

    if re.search(
        r"ejercicio|respiraci[oó]n|respirar 5 minutos|probemos juntos|herramienta|t[eé]cnica breve|short exercise|breathing exercise",
        reply,
        re.I,
    ):
        if not state.get("active_ficha_id"):
            state["pending_ficha_id"] = await choose_ficha(
                openai_client, user_message + " " + reply, fichas, prefer_calming=False
            )

    print("[FICHA STEP] none (conversation)")
    state["last_mode"] = "practical" if practical else "clinical"
    return {"output_message": reply, "profile": state, "mode": state["last_mode"]}