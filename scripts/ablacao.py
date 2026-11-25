#!/usr/bin/env python3
"""Ablação das mudanças candidatas às strings: volume no snapshot e sensibilidade
no conjunto de validação, uma mudança de cada vez (etapa determinística do
refinamento; a escolha da nova versão cabe às pessoas da equipe).

Uso: python3 scripts/ablacao.py data/raw/arxiv/cs.SE_2021-01_2026-11.jsonl
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from src.busca import Bloco, Familia, Matcher, carregar_config, texto_busca  # noqa: E402

# Mudanças candidatas, cada uma com a evidência literal que a justifica
NOVOS_CON = ["coding agent*", "AI coding", "coding tool*", "context file*", "AGENTS.md"]
NOVOS_TES = ["differential test*"]
FAMILIA_TRV = Familia(id="TRV", stage="cross-cutting", label="Gestão e governança (transversal)",
                      terms=["governance", "terms of service", "AI polic*", "contribution guideline*"])


def variantes(v1, v2_pratica):
    sem_sw = copy.deepcopy(v1)
    sem_sw.dominio = [b for b in sem_sw.dominio if b.id != "software"]
    termos = copy.deepcopy(sem_sw)
    termos.familias["CON"].terms += NOVOS_CON
    termos.familias["TES"].terms += NOVOS_TES
    trv = copy.deepcopy(termos)
    trv.familias["TRV"] = FAMILIA_TRV
    pratica = next(b for b in v2_pratica.dominio if b.id == "pratica")
    com_p = copy.deepcopy(termos)
    com_p.dominio.append(copy.deepcopy(pratica))
    com_p_trv = copy.deepcopy(trv)
    com_p_trv.dominio.append(copy.deepcopy(pratica))
    return [
        ("v1: IA ∧ software ∧ etapa", v1),
        ("sem o bloco de software", sem_sw),
        ("+ termos de agentes (CON) e de teste (TES)", termos),
        ("+ família transversal (gestão e governança)", trv),
        ("+ bloco de prática (sem a transversal)", com_p),
        ("+ bloco de prática (com a transversal)", com_p_trv),
    ]


def main() -> None:
    snap_path = Path(sys.argv[1])
    if not snap_path.is_absolute():
        snap_path = RAIZ / snap_path
    snap = [json.loads(l) for l in snap_path.read_text(encoding="utf-8").splitlines()]
    por_id = {r["id"]: r for r in snap}
    val = json.loads((RAIZ / "data" / "refinamento" / "validacao_q1.json").read_text(encoding="utf-8"))
    val_ids = [v["arxiv"] for v in val["itens"] if v.get("no_snapshot")]
    v1 = carregar_config()
    v2p = carregar_config(RAIZ / "config" / "variante_pratica.yaml")
    textos = {r["id"]: texto_busca(r) for r in snap}

    linhas = []
    for nome, cfg in variantes(v1, v2p):
        m = Matcher(cfg)
        vol, uniao = {f: 0 for f in cfg.familias}, 0
        for r in snap:
            fams = m.casar(textos[r["id"]])["familias"]
            uniao += bool(fams)
            for f in fams:
                vol[f] += 1
        recuperados = [i for i in val_ids if m.casar(textos[i])["familias"]]
        linhas.append({"variante": nome, "query_fingerprint": cfg.fingerprint(), "volume_por_familia": vol,
                       "uniao": uniao, "validacao_recuperados": len(recuperados),
                       "validacao_no_snapshot": len(val_ids),
                       "sensibilidade": round(len(recuperados) / len(val_ids), 3),
                       "nao_recuperados": [por_id[i]["title"] for i in val_ids if i not in recuperados]})
        fam_txt = "  ".join(f"{k}={v}" for k, v in vol.items())
        print(f"{nome:<46} união={uniao:>5}  sens={len(recuperados)}/{len(val_ids)}  | {fam_txt}")
    destino = RAIZ / "data" / "refinamento" / "ablacao_q1.json"
    destino.write_text(json.dumps({"evidencia": {
        "CON": "coding agent (Wink; Operationalizing Ethics...), AI coding (Operationalizing...; Accountable Agents...; "
               "A Dataset of Agentic AI Coding Tool Configurations), coding tool e context file (A Dataset...), "
               "AGENTS.md (Operationalizing Ethics...)",
        "TES": "differential testing (LLMs in the Heart of Differential Testing...)",
        "TRV": "governance (From Assistance to Agency...; Operationalizing...; Accountable Agents...), terms of service "
               "(Accountable Agents...); AI polic* e contribution guideline* vêm dos títulos de Hora, Robbes e Zacchiroli "
               "(2026) e de Hora e Robbes (2026), do conjunto de desenvolvimento",
        "software": "From Assistance to Agency... casa CI/CD (OPE), mas não tem termo do bloco de software"},
        "variantes": linhas}, indent=2, ensure_ascii=False))
    print(f"Ablação: {destino.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
