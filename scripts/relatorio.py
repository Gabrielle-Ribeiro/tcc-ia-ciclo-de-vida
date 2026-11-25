#!/usr/bin/env python3
"""Validação da string contra um conjunto de referência e amostra para a triagem.

1. Conjunto de validação: artigos do AIware 2024–2026 que o piloto anterior
   marcou como "incluir" ou excluiu por E4 (IA como ferramenta em uma
   atividade da ES), procurados no snapshot do arXiv pelo título.
   Sensibilidade = encontrados que a string recupera / encontrados no snapshot.
2. Amostra estratificada (n por família, semente fixa) dos registros que
   casaram, para a triagem pelo LLM.

Uso: python3 scripts/relatorio.py data/raw/arxiv/cs.SE_2021-01_2026-11.jsonl --n 15
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import random
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from src.busca import Matcher, carregar_config, texto_busca  # noqa: E402

CSV_AIWARE = RAIZ.parent / "piloto-aiware" / "triagem-aiware-2024-2026.csv"
SEMENTE = 20261117


def chave_titulo(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def carregar_validacao() -> list[dict]:
    linhas = list(csv.DictReader(open(CSV_AIWARE, encoding="utf-8"), delimiter=";"))
    return [r for r in linhas
            if r["decisao_ia"] == "incluir" or (r["decisao_ia"] == "excluir" and r["criterio_ia"].startswith("E4"))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot")
    ap.add_argument("--n", type=int, default=15)
    args = ap.parse_args()
    snap = Path(args.snapshot)
    if not snap.is_absolute():
        snap = RAIZ / snap
    cfg = carregar_config()
    matcher = Matcher(cfg)
    registros = [json.loads(l) for l in snap.read_text(encoding="utf-8").splitlines()]
    por_titulo = {chave_titulo(r["title"]): r for r in registros}
    titulos = list(por_titulo)

    # 1. Validação
    validacao = []
    for v in carregar_validacao():
        k = chave_titulo(v["titulo"])
        rec = por_titulo.get(k)
        if rec is None:
            perto = difflib.get_close_matches(k, titulos, n=1, cutoff=0.9)
            rec = por_titulo[perto[0]] if perto else None
        item = {"id_aiware": v["id"], "ano": v["ano"], "titulo": v["titulo"],
                "decisao_piloto_anterior": v["decisao_ia"], "criterio": v["criterio_ia"],
                "no_snapshot": rec is not None}
        if rec is not None:
            res = matcher.casar(texto_busca(rec))
            item.update({"arxiv": rec["id"], "familias": sorted(res["familias"]),
                         "casou": bool(res["familias"]),
                         "bloco_ia": res["dominio"]["ia"], "bloco_software": res["dominio"]["software"]})
        validacao.append(item)
    achados = [v for v in validacao if v["no_snapshot"]]
    casados = [v for v in achados if v["casou"]]
    sens = len(casados) / len(achados) if achados else 0.0
    destino_val = RAIZ / "data" / "refinamento" / f"validacao_q{cfg.version}.json"
    destino_val.write_text(json.dumps({
        "query_version": cfg.version, "query_fingerprint": cfg.fingerprint(),
        "conjunto": "AIware 2024–2026: incluídos no piloto anterior + excluídos por E4",
        "tamanho": len(validacao), "no_snapshot_arxiv": len(achados),
        "recuperados_pela_string": len(casados), "sensibilidade": round(sens, 3),
        "itens": validacao}, indent=2, ensure_ascii=False))
    print(f"Validação: {len(validacao)} no conjunto; {len(achados)} no snapshot do arXiv; "
          f"{len(casados)} recuperados (sensibilidade {sens:.2f})")
    for v in achados:
        if not v["casou"]:
            print(f"  NÃO recuperado: {v['titulo'][:90]}  | IA={v['bloco_ia'][:2]} SW={v['bloco_software'][:2]}")

    # 2. Amostra estratificada
    pasta = RAIZ / "data" / "matched" / f"q{cfg.version}"
    rng = random.Random(SEMENTE)
    ja, amostra = set(), []
    for fam in cfg.familias.values():
        subset = [json.loads(l) for l in (pasta / f"{fam.id}.jsonl").read_text(encoding="utf-8").splitlines()]
        subset = [r for r in subset if r["id"] not in ja]
        escolhidos = rng.sample(subset, min(args.n, len(subset)))
        for r in escolhidos:
            ja.add(r["id"])
            amostra.append({"id": r["id"], "familia_amostrada": fam.id, "search_families": r["search_families"],
                            "title": r["title"], "abstract": r["abstract"], "published": r["published"]})
    destino = RAIZ / "data" / "amostra" / f"amostra_q{cfg.version}.jsonl"
    with open(destino, "w", encoding="utf-8") as fh:
        for r in amostra:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Amostra: {len(amostra)} registros ({args.n} por família, semente {SEMENTE}) em {destino.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
