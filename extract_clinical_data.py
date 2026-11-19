"""Parse protocolo_constanza.txt into clinical_data/plan_b.json and fichas.json."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROTOCOL_PATH = ROOT / "protocolo_constanza.txt"
CLINICAL_DIR = ROOT / "clinical_data"


def _clean_quote(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s*\(ESPERA RESPUESTA\)\s*", "", text, flags=re.IGNORECASE)
    text = text.strip().strip('"').strip("“”").strip()
    return re.sub(r"\s+", " ", text).strip()


def extract_plan_b(protocol: str) -> dict:
    section = protocol.split("SECCIÓN 3:", 1)[1].split("SECCIÓN 4:", 1)[0]
    scenarios = {}
    letters = ["A", "B", "C", "D"]
    for i, letter in enumerate(letters):
        start = section.find(f"ESCENARIO {letter}:")
        if start == -1:
            raise ValueError(f"Missing ESCENARIO {letter}")
        if i + 1 < len(letters):
            end = section.find(f"ESCENARIO {letters[i + 1]}:")
        else:
            end = len(section)
        block = section[start:end].strip()
        header_match = re.match(
            r"ESCENARIO [A-D]:\s*(.+?)(?:\s*\(Se activa ante:|\s*\(Se activa si,)",
            block,
            re.DOTALL,
        )
        trigger_match = re.search(r"\(Se activa (?:ante|si,)(.+?)\)", block, re.DOTALL)
        body_match = re.search(
            r"\(Se activa (?:ante|si,).+?\)\s*(.+)$",
            block,
            re.DOTALL,
        )
        if not body_match:
            raise ValueError(f"Could not parse body of ESCENARIO {letter}")
        scenarios[letter] = {
            "id": letter,
            "title": f"ESCENARIO {letter}: {header_match.group(1).strip()}" if header_match else f"ESCENARIO {letter}",
            "activates_when": " ".join(trigger_match.group(1).split()).strip() if trigger_match else "",
            "message": body_match.group(1).strip(),
            "verbatim": block,
        }
    return {
        "source": "SECCIÓN 3: MENSAJES DE DERIVACIÓN DINÁMICA (PLAN B)",
        "scenarios": scenarios,
    }


def extract_fichas(protocol: str) -> dict:
    section = protocol.split("SECCIÓN 4:", 1)[1].split("SECCIÓN 5:", 1)[0]
    chunks = re.split(r"\n(?=FICHA \d+:)", section)
    fichas = []
    for chunk in chunks:
        match = re.match(r"FICHA (\d+):\s*(.+)", chunk.strip())
        if not match:
            continue
        number = int(match.group(1))
        if number < 1 or number > 38:
            continue
        title = match.group(2).strip()
        objetivo = ""
        cuando = ""
        obj = re.search(r"Objetivo clínico:\s*(.+)", chunk)
        when = re.search(r"Cu[aá]ndo usarla:\s*(.+)", chunk)
        if obj:
            objetivo = obj.group(1).strip()
        if when:
            cuando = when.group(1).strip()

        guion_split = re.split(r"Gui[oó]n Interactivo:\s*", chunk, maxsplit=1)
        guion = guion_split[1] if len(guion_split) > 1 else chunk
        step1_match = re.search(
            r"(?:Acción directa|Psicoeducación y Permiso):\s*\"([^\"]+)\"",
            guion,
        )
        step2_match = re.search(
            r"(?:Ejecución|Evaluación y Derivación):\s*\"([^\"]+)\"",
            guion,
        )
        step3_match = re.search(r"Cierre \(Sentido\):\s*\"([^\"]+)\"", guion)
        if not (step1_match and step2_match and step3_match):
            raise ValueError(f"Ficha {number} does not have 3 script steps")
        steps = [
            _clean_quote(step1_match.group(1)),
            _clean_quote(step2_match.group(1)),
            _clean_quote(step3_match.group(1)),
        ]
        fichas.append(
            {
                "id": number,
                "title": title,
                "objetivo_clinico": objetivo,
                "cuando_usarla": cuando,
                "step_1": steps[0],
                "step_2": steps[1],
                "step_3": steps[2],
            }
        )

    fichas.sort(key=lambda f: f["id"])
    ids = [f["id"] for f in fichas]
    missing = [n for n in range(1, 39) if n not in ids]
    if missing:
        raise ValueError(f"Missing fichas: {missing}")
    return {"source": "SECCIÓN 4: EL BANCO DE RECURSOS", "count": len(fichas), "fichas": fichas}


def extract_all(force: bool = False) -> tuple[Path, Path]:
    CLINICAL_DIR.mkdir(exist_ok=True)
    plan_path = CLINICAL_DIR / "plan_b.json"
    fichas_path = CLINICAL_DIR / "fichas.json"
    if not force and plan_path.exists() and fichas_path.exists():
        return plan_path, fichas_path

    protocol = PROTOCOL_PATH.read_text(encoding="utf-8")
    plan_b = extract_plan_b(protocol)
    fichas = extract_fichas(protocol)
    plan_path.write_text(json.dumps(plan_b, ensure_ascii=False, indent=2), encoding="utf-8")
    fichas_path.write_text(json.dumps(fichas, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Extracted {len(plan_b['scenarios'])} Plan B scenarios -> {plan_path}")
    print(f"Extracted {fichas['count']} fichas -> {fichas_path}")
    return plan_path, fichas_path


if __name__ == "__main__":
    extract_all(force=True)
