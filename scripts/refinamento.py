#!/usr/bin/env python3
"""Pacote de refinamento: desempenho de cada termo na amostra triada e efeito
de um bloco candidato (ex.: bloco de prática) sobre volume e revocação.

Etapa determinística do ciclo de refinamento do metodologia-tcc: o pacote
alimenta a proposta de nova versão, que só vale depois de aprovada por pessoas.

Uso:
  python3 scripts/refinamento.py data/amostra/triagem_llm_q1.csv \
      --snapshot data/raw/arxiv/cs.SE_2021-01_2026-11.jsonl \
      --candidato config/proposta_q2.yaml
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from src.busca import Matcher, carregar_config, normalizar, termos_casados, texto_busca  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("decisoes")
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--candidato", help="YAML de uma versão candidata (mesma estrutura)")
    args = ap.parse_args()
    cfg = carregar_config()
    matcher = Matcher(cfg)

    amostra = {json.loads(l)["id"]: json.loads(l)
               for l in (RAIZ / "data" / "amostra" / f"amostra_q{cfg.version}.jsonl").read_text(encoding="utf-8").splitlines()}
    decisoes = {r["id"]: r for r in csv.DictReader(open(RAIZ / args.decisoes, encoding="utf-8"), delimiter=";")}

    # Precisão por família (na família de onde o registro foi amostrado) e por termo
    por_familia = collections.defaultdict(collections.Counter)
    por_termo = collections.defaultdict(collections.Counter)
    criterios = collections.Counter()
    etapa_llm = collections.defaultdict(collections.Counter)
    for pid, d in decisoes.items():
        rec = amostra[pid]
        por_familia[rec["familia_amostrada"]][d["decisao"]] += 1
        criterios[d["criterio"]] += 1
        etapa_llm[rec["familia_amostrada"]][d.get("etapa", "")] += 1
        res = matcher.casar(texto_busca(rec))
        for fam, termos in res["familias"].items():
            for t in termos:
                por_termo[(fam, t)][d["decisao"]] += 1

    familias = {}
    for fid, c in por_familia.items():
        n = sum(c.values())
        familias[fid] = {"triados": n, "incluir": c["incluir"], "duvida": c["duvida"], "excluir": c["excluir"],
                         "precisao_estrita": round(c["incluir"] / n, 3) if n else None,
                         "precisao_com_duvidas": round((c["incluir"] + c["duvida"]) / n, 3) if n else None,
                         "etapa_atribuida_pelo_llm": dict(etapa_llm[fid])}
    termos = [{"familia": f, "termo": t, "revisados": sum(c.values()), "incluidos": c["incluir"],
               "duvidas": c["duvida"], "precisao_observada": round(c["incluir"] / sum(c.values()), 3)}
              for (f, t), c in por_termo.items()]
    termos.sort(key=lambda x: (x["precisao_observada"], -x["revisados"]))

    pacote = {
        "gerado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "query_version": cfg.version, "query_fingerprint": cfg.fingerprint(),
        "decisoes": args.decisoes, "n_decisoes": len(decisoes),
        "por_familia": familias, "criterios": dict(criterios.most_common()),
        "desempenho_dos_termos": termos,
    }

    # Efeito de uma versão candidata: volume no snapshot e revocação na amostra
    if args.candidato:
        cand = carregar_config(RAIZ / args.candidato)
        mc = Matcher(cand)
        snap = [json.loads(l) for l in (RAIZ / args.snapshot).read_text(encoding="utf-8").splitlines()]
        vol_atual, vol_cand = collections.Counter(), collections.Counter()
        uniao_atual = uniao_cand = 0
        for r in snap:
            t = texto_busca(r)
            a = matcher.casar(t)["familias"]
            b = mc.casar(t)["familias"]
            uniao_atual += bool(a)
            uniao_cand += bool(b)
            for f in a:
                vol_atual[f] += 1
            for f in b:
                vol_cand[f] += 1
        rev = collections.Counter()
        for pid, d in decisoes.items():
            casa = bool(mc.casar(texto_busca(amostra[pid]))["familias"])
            rev[(d["decisao"], casa)] += 1
        inc_tot = rev[("incluir", True)] + rev[("incluir", False)]
        exc_tot = rev[("excluir", True)] + rev[("excluir", False)]
        pacote["candidato"] = {
            "arquivo": args.candidato, "query_fingerprint": cand.fingerprint(),
            "volume_por_familia": {f: {"atual": vol_atual[f], "candidato": vol_cand[f]} for f in cfg.familias},
            "volume_uniao": {"atual": uniao_atual, "candidato": uniao_cand},
            "amostra": {
                "incluidos_mantidos": rev[("incluir", True)], "incluidos_perdidos": rev[("incluir", False)],
                "duvidas_mantidas": rev[("duvida", True)], "duvidas_perdidas": rev[("duvida", False)],
                "excluidos_mantidos": rev[("excluir", True)], "excluidos_removidos": rev[("excluir", False)],
                "revocacao_dos_incluidos": round(rev[("incluir", True)] / inc_tot, 3) if inc_tot else None,
                "fracao_dos_excluidos_removida": round(rev[("excluir", False)] / exc_tot, 3) if exc_tot else None,
            },
        }

    sufixo = f"_{Path(args.candidato).stem}" if args.candidato else ""
    destino = RAIZ / "data" / "refinamento" / f"pacote_q{cfg.version}_amostra{sufixo}.json"
    destino.write_text(json.dumps(pacote, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in pacote.items() if k != "desempenho_dos_termos"}, indent=2, ensure_ascii=False))
    print(f"Pacote: {destino.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
