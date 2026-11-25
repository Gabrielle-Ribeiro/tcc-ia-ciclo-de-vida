#!/usr/bin/env python3
"""Conta, no OpenAlex, quantos registros cada família recupera (estimativa de volume).

O OpenAlex é usado aqui como aproximação de uma base multidisciplinar, como a
Scopus: aceita busca booleana em título e resumo, mas não aceita curinga (o
'*' é removido e vale o stemming da própria base). Só as contagens são
coletadas; os registros não são baixados, por causa do limite diário de uso.

Uso: python3 scripts/contar_openalex.py [--desde 2021-01-01]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from src.busca import carregar_config, query_openalex, query_openalex_uniao  # noqa: E402

API = "https://api.openalex.org/works"
AGENTE = "piloto-revisao-multivocal/0.1 (pesquisa academica)"


def contar(query: str, desde: str, extra: str = "") -> tuple[int | None, dict, str | None]:
    params = urllib.parse.urlencode({
        "filter": f"title_and_abstract.search:{query},from_publication_date:{desde}" + (f",{extra}" if extra else ""),
        "per-page": 1,
        "select": "id",
    })
    req = urllib.request.Request(f"{API}?{params}", headers={"User-Agent": AGENTE})
    for tentativa in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                corpo = json.loads(resp.read().decode("utf-8"))
                limites = {k: v for k, v in resp.headers.items() if k.lower().startswith("x-ratelimit")}
                return corpo["meta"]["count"], limites, None
        except Exception as exc:
            erro = str(exc)
            time.sleep(5 * (tentativa + 1))
    return None, {}, erro


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default="2021-01-01")
    ap.add_argument("--config", default=None, help="YAML de strings (padrão: config/search_queries.yaml)")
    ap.add_argument("--filtro", default="", help="filtro extra do OpenAlex, ex.: primary_topic.field.id:17 (Computer Science)")
    args = ap.parse_args()
    cfg = carregar_config(RAIZ / args.config) if args.config else carregar_config()
    inicio = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    consultas = {"DOMINIO": query_openalex(cfg, None)}
    for fam in cfg.familias.values():
        consultas[fam.id] = query_openalex(cfg, fam)
    consultas["UNIAO"] = query_openalex_uniao(cfg)

    resultados, ultimo_limite = {}, {}
    for chave, q in consultas.items():
        n, limites, erro = contar(q, args.desde, args.filtro)
        ultimo_limite = limites or ultimo_limite
        resultados[chave] = {"executed_query": q, "count": n, "error": erro}
        rotulo = cfg.familias[chave].label if chave in cfg.familias else chave
        print(f"{chave:<14} {rotulo:<14} {n if n is not None else 'ERRO: ' + str(erro)}", flush=True)
        time.sleep(1.5)

    manifesto = {
        "source": "openalex",
        "endpoint": API,
        "executed_at": inicio,
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "query_version": cfg.version,
        "config": args.config or "config/search_queries.yaml",
        "query_fingerprint": cfg.fingerprint(),
        "search_fields": ["title", "abstract"],
        "adapter": "title_and_abstract.search; '*' removido (a base usa stemming e não aceita curinga)",
        "temporal_filter": f"from_publication_date:{args.desde}",
        "filtro_extra": args.filtro or None,
        "observacao": "só contagens; os registros não foram baixados",
        "resultados": resultados,
        "rate_limit_final": ultimo_limite,
    }
    destino = RAIZ / "data" / "manifests" / "openalex" / f"{dt.datetime.now().strftime('%Y-%m-%dT%H%M%S')}-contagens.json"
    destino.write_text(json.dumps(manifesto, indent=2, ensure_ascii=False))
    print(f"Manifesto: {destino}")


if __name__ == "__main__":
    main()
