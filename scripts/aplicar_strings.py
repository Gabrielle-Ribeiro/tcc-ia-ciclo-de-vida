#!/usr/bin/env python3
"""Aplica as strings ao snapshot do arXiv com o matcher local e grava o manifesto.

Saídas:
  data/matched/q<versão>/<FAMÍLIA>.jsonl   registros de cada família, com os termos casados
  data/matched/q<versão>/todos.jsonl       todos os registros que casaram alguma família
  data/manifests/arxiv/<data>-matching.json

Uso: python3 scripts/aplicar_strings.py data/raw/arxiv/cs.SE_2021-01_2026-11.jsonl
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from src.busca import Matcher, carregar_config, query_canonica, query_scopus, texto_busca  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot")
    args = ap.parse_args()
    snap = Path(args.snapshot)
    if not snap.is_absolute():
        snap = RAIZ / snap
    cfg = carregar_config()
    matcher = Matcher(cfg)
    inicio = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    registros = [json.loads(linha) for linha in snap.read_text(encoding="utf-8").splitlines()]
    stats = collections.Counter()
    por_ano = collections.defaultdict(collections.Counter)
    sem_software = collections.Counter()
    casados = []
    for r in registros:
        res = matcher.casar(texto_busca(r))
        dom = res["dominio"]
        stats["varridos"] += 1
        if not r.get("abstract"):
            stats["sem_resumo"] += 1
        if dom["ia"]:
            stats["bloco_ia"] += 1
            if dom["software"]:
                stats["bloco_ia_e_software"] += 1
            # diagnóstico: quantos casariam alguma família sem o bloco de software
            sem = matcher.casar(texto_busca(r), exigir_software=False)
            for fid in sem["familias"]:
                sem_software[fid] += 1
        if res["familias"]:
            r2 = {k: r.get(k) for k in ("id", "title", "abstract", "published", "primary_category", "doi", "journal_ref")}
            r2["search_families"] = sorted(res["familias"])
            r2["matched_terms"] = res["familias"]
            r2["domain_terms"] = dom
            casados.append(r2)
            ano = (r.get("published") or "????")[:4]
            for fid in res["familias"]:
                por_ano[fid][ano] += 1

    pasta = RAIZ / "data" / "matched" / f"q{cfg.version}"
    pasta.mkdir(parents=True, exist_ok=True)
    with open(pasta / "todos.jsonl", "w", encoding="utf-8") as fh:
        for r in casados:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    familias = {}
    for fam in cfg.familias.values():
        subset = [r for r in casados if fam.id in r["search_families"]]
        with open(pasta / f"{fam.id}.jsonl", "w", encoding="utf-8") as fh:
            for r in subset:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        termos = collections.Counter(t for r in subset for t in r["matched_terms"][fam.id])
        familias[fam.id] = {
            "stage": fam.stage,
            "label": fam.label,
            "canonical_query": query_canonica(cfg, fam),
            "scopus_query": query_scopus(cfg, fam),
            "total_results": len(subset),
            "total_sem_bloco_software": sem_software[fam.id],
            "por_ano": dict(sorted(por_ano[fam.id].items())),
            "termos_que_casaram": dict(termos.most_common()),
            "termos_sem_ocorrencia": [t for t in fam.terms if t not in termos],
            "output_file": str((pasta / f"{fam.id}.jsonl").relative_to(RAIZ)),
        }
    n_fams = collections.Counter(len(r["search_families"]) for r in casados)
    manifesto = {
        "source": "arxiv",
        "executed_at": inicio,
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "search_mode": "local_metadata_matching",
        "search_fields": ["title", "abstract"],
        "text_normalization": "unicode NFKC, traços unicode→'-', minúsculas, espaços colapsados; sem stemming",
        "query_version": cfg.version,
        "query_fingerprint": cfg.fingerprint(),
        "snapshot": str(snap.relative_to(RAIZ)),
        "snapshot_sha256": hashlib.sha256(snap.read_bytes()).hexdigest(),
        "stats": dict(stats),
        "families": familias,
        "unique_papers": len(casados),
        "total_occurrences": sum(f["total_results"] for f in familias.values()),
        "registros_por_numero_de_familias": dict(sorted(n_fams.items())),
    }
    destino = RAIZ / "data" / "manifests" / "arxiv" / f"{dt.datetime.now().strftime('%Y-%m-%dT%H%M%S')}-matching.json"
    destino.write_text(json.dumps(manifesto, indent=2, ensure_ascii=False))

    print(f"Registros varridos: {stats['varridos']}  |  bloco IA: {stats['bloco_ia']}  |  IA e software: {stats['bloco_ia_e_software']}")
    for fid, f in familias.items():
        print(f"{fid} {f['label']:<12} {f['total_results']:>6}   (sem o bloco de software: {f['total_sem_bloco_software']})")
    print(f"Ocorrências: {manifesto['total_occurrences']}  |  registros únicos: {len(casados)}")
    print(f"Manifesto: {destino}")


if __name__ == "__main__":
    main()
