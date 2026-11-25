"""Strings de busca: carregamento, versionamento, queries por base e matcher local.

Segue o desenho do repositório metodologia-tcc: um único YAML define as
strings; as queries de cada base e o matcher local são gerados daqui.

Forma de toda busca:  (IA) AND (SOFTWARE) AND (ETAPA)
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]
CONFIG_PADRAO = RAIZ / "config" / "search_queries.yaml"


# --------------------------------------------------------------------------- #
# Configuração
# --------------------------------------------------------------------------- #

@dataclass
class Bloco:
    id: str
    label: str
    terms: list[str]


@dataclass
class Familia:
    id: str
    stage: str
    label: str
    terms: list[str]


@dataclass
class ConfigBusca:
    version: int
    dominio: list[Bloco]
    familias: dict[str, Familia] = field(default_factory=dict)

    def fingerprint(self) -> str:
        """SHA-256 só dos termos: comentários e formatação do YAML não contam."""
        payload = {
            "domain": {b.id: b.terms for b in self.dominio},
            "families": {f.id: f.terms for f in self.familias.values()},
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def carregar_config(caminho: Path | str = CONFIG_PADRAO) -> ConfigBusca:
    with open(caminho, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    dominio = [Bloco(id=k, label=v["label"], terms=list(v["terms"])) for k, v in raw["domain"].items()]
    familias = {
        fid: Familia(id=fid, stage=spec["stage"], label=spec["label"], terms=list(spec["terms"]))
        for fid, spec in raw["families"].items()
    }
    for bloco in dominio:
        assert bloco.terms, f"bloco vazio: {bloco.id}"
    for fam in familias.values():
        assert fam.terms, f"família vazia: {fam.id}"
    return ConfigBusca(version=int(raw.get("version", 1)), dominio=dominio, familias=familias)


# --------------------------------------------------------------------------- #
# Queries por base
# --------------------------------------------------------------------------- #

def formatar_termo(termo: str) -> str:
    """Frases (com espaço ou hífen) vão entre aspas; palavras simples, não."""
    if " " in termo or "-" in termo or "/" in termo:
        return f'"{termo}"'
    return termo


def bloco_or(termos: list[str], fmt=formatar_termo) -> str:
    return "(" + " OR ".join(fmt(t) for t in termos) + ")"


def query_canonica(cfg: ConfigBusca, fam: Familia) -> str:
    blocos = [bloco_or(b.terms) for b in cfg.dominio] + [bloco_or(fam.terms)]
    return " AND ".join(blocos)


def query_scopus(cfg: ConfigBusca, fam: Familia, ano_inicial: int = 2021) -> str:
    """Scopus aceita frases com curinga; a query canônica vai em TITLE-ABS-KEY."""
    return f"TITLE-ABS-KEY({query_canonica(cfg, fam)}) AND PUBYEAR > {ano_inicial - 1}"


# Radicais com curinga que não são palavras: no OpenAlex viram as formas completas.
EXPANSOES_OPENALEX = {
    "programm*": ["programming", "programmer"],
    "repositor*": ["repository", "repositories"],
    "stor*": ["story", "stories"],
    "summar*": ["summarization", "summary"],
    "pars*": ["parsing", "parser"],
    "architect*": ["architecture", "architect"],
    "prototyp*": ["prototype", "prototyping"],
    "fuzz*": ["fuzzing", "fuzzer"],
    "refactor*": ["refactoring", "refactor"],
}


def _termo_openalex(termo: str) -> str:
    """OpenAlex não aceita curinga, mas aplica stemming: remove-se o '*'.

    Quando o radical não é uma palavra (programm*, repositor*), usam-se as
    formas completas listadas em EXPANSOES_OPENALEX.
    """
    import itertools

    opcoes = []
    for palavra in termo.split(" "):
        chave = palavra.lower()
        if chave in EXPANSOES_OPENALEX:
            opcoes.append(EXPANSOES_OPENALEX[chave])
        else:
            opcoes.append([palavra[:-1] if palavra.endswith("*") else palavra])
    variantes = [" ".join(c) for c in itertools.product(*opcoes)]

    def citar(v: str) -> str:
        return f'"{v}"' if (" " in v or "-" in v or "/" in v) else v

    if len(variantes) == 1:
        return citar(variantes[0])
    return "(" + " OR ".join(citar(v) for v in variantes) + ")"


def query_openalex(cfg: ConfigBusca, fam: Familia | None) -> str:
    blocos = [bloco_or(b.terms, _termo_openalex) for b in cfg.dominio]
    if fam is not None:
        blocos.append(bloco_or(fam.terms, _termo_openalex))
    return " AND ".join(blocos)


def query_openalex_uniao(cfg: ConfigBusca) -> str:
    todos = [t for f in cfg.familias.values() for t in f.terms]
    vistos, unicos = set(), []
    for t in todos:
        if t not in vistos:
            vistos.add(t)
            unicos.append(t)
    blocos = [bloco_or(b.terms, _termo_openalex) for b in cfg.dominio] + [bloco_or(unicos, _termo_openalex)]
    return " AND ".join(blocos)


# --------------------------------------------------------------------------- #
# Normalização e matcher local (mesma semântica do metodologia-tcc)
# --------------------------------------------------------------------------- #

_TRACOS = re.compile(r"[‐‑‒–—−­]")
_ESPACOS = re.compile(r"\s+")


def normalizar(texto: str | None) -> str:
    """NFKC, traços unificados, minúsculas e espaços colapsados; sem stemming."""
    if not texto:
        return ""
    texto = unicodedata.normalize("NFKC", texto)
    texto = _TRACOS.sub("-", texto)
    return _ESPACOS.sub(" ", texto.lower()).strip()


@lru_cache(maxsize=None)
def compilar_termo(termo: str) -> re.Pattern[str]:
    palavras = normalizar(termo).split(" ")
    partes = [re.escape(p[:-1]) + r"\w*" if p.endswith("*") else re.escape(p) for p in palavras]
    padrao = r"(?<!\w)" + r"\s+".join(partes)
    if not palavras[-1].endswith("*"):
        padrao += r"(?!\w)"
    return re.compile(padrao)


def termos_casados(texto_norm: str, termos: list[str]) -> list[str]:
    return [t for t in termos if compilar_termo(t).search(texto_norm)]


class Matcher:
    """Aplica os blocos de domínio (todos obrigatórios) e depois cada família."""

    def __init__(self, cfg: ConfigBusca):
        self.cfg = cfg

    def dominio(self, texto_norm: str) -> dict[str, list[str]]:
        return {b.id: termos_casados(texto_norm, b.terms) for b in self.cfg.dominio}

    def casar(self, texto: str, exigir_software: bool = True) -> dict:
        """Retorna os termos casados por bloco e as famílias satisfeitas."""
        norm = normalizar(texto)
        dom = self.dominio(norm)
        ok_dom = all(dom[b.id] for b in self.cfg.dominio if exigir_software or b.id != "software")
        familias = {}
        if ok_dom:
            for fam in self.cfg.familias.values():
                hits = termos_casados(norm, fam.terms)
                if hits:
                    familias[fam.id] = hits
        return {"dominio": dom, "dominio_ok": ok_dom, "familias": familias}


def texto_busca(registro: dict) -> str:
    """Título + resumo, como no metodologia-tcc."""
    return f"{registro.get('title') or ''} {registro.get('abstract') or ''}"
