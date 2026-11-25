#!/usr/bin/env python3
"""Coleta o snapshot do arXiv cs.SE (por mês de submissão) para o matcher local.

A API do arXiv aplica stemming e não respeita o curinga "*" (elicit*, elicit e
elicitation devolvem o mesmo total). Por isso, como o metodologia-tcc faz com a
ACL Anthology, baixamos todos os registros da categoria no período e aplicamos
as strings localmente (scripts/aplicar_strings.py).

Uso: python3 scripts/coletar_arxiv.py --inicio 2021-01 --fim 2026-11
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
API = "https://export.arxiv.org/api/query"
NS = {
    "a": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "os": "http://a9.com/-/spec/opensearch/1.1/",
}
AGENTE = "piloto-revisao-multivocal/0.1 (pesquisa academica)"
POR_PAGINA = 1000
PAUSA = 3.2


def agora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def meses(inicio: str, fim: str):
    a, m = map(int, inicio.split("-"))
    af, mf = map(int, fim.split("-"))
    while (a, m) <= (af, mf):
        yield a, m
        m += 1
        if m == 13:
            a, m = a + 1, 1


def query_mes(categoria: str, ano: int, mes: int) -> str:
    ultimo = calendar.monthrange(ano, mes)[1]
    return f"cat:{categoria} AND submittedDate:[{ano:04d}{mes:02d}010000 TO {ano:04d}{mes:02d}{ultimo:02d}2359]"


def chamar(query: str, inicio: int, n: int) -> str:
    params = urllib.parse.urlencode({
        "search_query": query, "start": inicio, "max_results": n,
        "sortBy": "submittedDate", "sortOrder": "ascending",
    })
    req = urllib.request.Request(f"{API}?{params}", headers={"User-Agent": AGENTE})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read().decode("utf-8")


def _txt(el) -> str | None:
    return " ".join(el.text.split()) if el is not None and el.text else None


def interpretar(xml: str) -> tuple[int, list[dict]]:
    raiz = ET.fromstring(xml)
    total = int(raiz.find("os:totalResults", NS).text)
    registros = []
    for e in raiz.findall("a:entry", NS):
        eid = e.find("a:id", NS).text
        if "api/errors" in eid:
            raise RuntimeError("erro da API: " + (_txt(e.find("a:summary", NS)) or ""))
        arxiv_id = eid.rsplit("/abs/", 1)[-1]
        base_id = arxiv_id.rsplit("v", 1)[0] if "v" in arxiv_id.split("/")[-1] else arxiv_id
        prim = e.find("arxiv:primary_category", NS)
        registros.append({
            "id": f"arxiv:{base_id}",
            "arxiv_id": base_id,
            "versao": arxiv_id,
            "title": _txt(e.find("a:title", NS)),
            "abstract": _txt(e.find("a:summary", NS)),
            "published": (e.find("a:published", NS).text or "")[:10],
            "updated": (e.find("a:updated", NS).text or "")[:10],
            "authors": [_txt(a.find("a:name", NS)) for a in e.findall("a:author", NS)],
            "primary_category": prim.get("term") if prim is not None else None,
            "categories": [c.get("term") for c in e.findall("a:category", NS)],
            "doi": _txt(e.find("arxiv:doi", NS)),
            "journal_ref": _txt(e.find("arxiv:journal_ref", NS)),
            "comment": _txt(e.find("arxiv:comment", NS)),
        })
    return total, registros


def coletar_mes(query: str, log) -> tuple[int, list[dict], str]:
    inicio, total, coletados = 0, None, []
    while True:
        for tentativa in range(7):
            try:
                total_pag, regs = interpretar(chamar(query, inicio, POR_PAGINA))
                if total_pag > inicio and not regs:
                    raise RuntimeError("página vazia com resultados pendentes")
                break
            except Exception as exc:  # rede, XML, erro da API
                espera = 5 * 2 ** tentativa
                log(f"  tentativa {tentativa + 1} falhou ({exc}); nova tentativa em {espera}s")
                time.sleep(espera)
        else:
            return total or 0, coletados, "incompleto"
        total = total_pag
        coletados += regs
        inicio += len(regs)
        time.sleep(PAUSA)
        if inicio >= total or not regs:
            return total, coletados, "completo"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--categoria", default="cs.SE")
    ap.add_argument("--inicio", default="2021-01")
    ap.add_argument("--fim", default="2026-11")
    args = ap.parse_args()

    pasta_meses = RAIZ / "data" / "raw" / "arxiv" / "meses"
    pasta_meses.mkdir(parents=True, exist_ok=True)
    estado_path = RAIZ / "data" / "raw" / "arxiv" / "estado_coleta.json"
    estado = json.loads(estado_path.read_text()) if estado_path.exists() else {}
    iniciado = agora()

    def log(msg: str) -> None:
        print(msg, flush=True)

    for ano, mes in meses(args.inicio, args.fim):
        chave = f"{ano:04d}-{mes:02d}"
        if estado.get(chave, {}).get("status") == "completo":
            continue
        query = query_mes(args.categoria, ano, mes)
        total, regs, status = coletar_mes(query, log)
        with open(pasta_meses / f"{chave}.jsonl", "w", encoding="utf-8") as fh:
            for r in regs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        estado[chave] = {"query": query, "total_informado": total, "coletados": len(regs), "status": status}
        estado_path.write_text(json.dumps(estado, indent=2, ensure_ascii=False))
        log(f"{chave}: {len(regs)}/{total} ({status})")

    # Snapshot único, sem duplicatas
    vistos, snapshot = set(), []
    for chave in sorted(estado):
        caminho = pasta_meses / f"{chave}.jsonl"
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            r = json.loads(linha)
            if r["id"] not in vistos:
                vistos.add(r["id"])
                snapshot.append(r)
    saida = RAIZ / "data" / "raw" / "arxiv" / f"{args.categoria}_{args.inicio}_{args.fim}.jsonl"
    with open(saida, "w", encoding="utf-8") as fh:
        for r in snapshot:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    sha = hashlib.sha256(saida.read_bytes()).hexdigest()

    manifesto = {
        "source": "arxiv",
        "endpoint": API,
        "executed_at": iniciado,
        "finished_at": agora(),
        "search_mode": "snapshot da categoria + matcher local",
        "motivo": "a API aplica stemming e ignora o curinga '*'; as strings são aplicadas localmente",
        "categoria": args.categoria,
        "periodo": {"inicio": args.inicio, "fim": args.fim, "campo_data": "submittedDate (versão 1)"},
        "por_mes": estado,
        "total_informado_soma": sum(v["total_informado"] for v in estado.values()),
        "coletados_soma": sum(v["coletados"] for v in estado.values()),
        "meses_incompletos": [k for k, v in estado.items() if v["status"] != "completo"],
        "registros_unicos": len(snapshot),
        "snapshot": str(saida.relative_to(RAIZ)),
        "snapshot_sha256": sha,
    }
    destino = RAIZ / "data" / "manifests" / "arxiv" / f"{dt.datetime.now().strftime('%Y-%m-%dT%H%M%S')}-coleta.json"
    destino.write_text(json.dumps(manifesto, indent=2, ensure_ascii=False))
    log(f"Snapshot: {saida} ({len(snapshot)} registros); manifesto: {destino}")
    if manifesto["meses_incompletos"]:
        log("ATENÇÃO: meses incompletos: " + ", ".join(manifesto["meses_incompletos"]))
        sys.exit(2)


if __name__ == "__main__":
    main()
