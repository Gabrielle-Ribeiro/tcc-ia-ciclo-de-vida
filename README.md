# Piloto da busca (pré-projeto por etapas do ciclo de vida)

Infraestrutura de busca da revisão, com o desenho adaptado do repositório
metodologia-tcc: as strings ficam em um único YAML, as consultas de cada base
são geradas por código, um hash SHA-256 dos termos identifica a versão e cada
coleta grava um manifesto. Os resultados estão na Seção 6.1 do pré-projeto.

## Arquivos

- `config/search_queries.yaml`: versão 1 das strings (IA AND software AND etapa).
- `config/proposta_q2.yaml`: proposta de versão 2 (IA AND etapa, com termos novos). Ainda não foi aprovada.
- `config/variante_pratica.yaml`: variante com o bloco de prática, testada e rejeitada (sensibilidade 0,59).
- `src/busca.py`: carrega o YAML, calcula o hash, gera as queries (canônica, Scopus e OpenAlex) e tem o matcher local.
- `scripts/coletar_arxiv.py`: baixa o snapshot de cs.SE, mês a mês, com retomada.
- `scripts/aplicar_strings.py`: aplica as strings ao snapshot e grava os registros por família e o manifesto.
- `scripts/relatorio.py`: mede a sensibilidade no conjunto de referência e sorteia a amostra para a triagem.
- `scripts/ablacao.py`: mede o efeito de cada mudança nas strings (volume e sensibilidade).
- `scripts/refinamento.py`: calcula a precisão de cada termo na amostra triada e o efeito de uma versão candidata.
- `scripts/contar_openalex.py`: conta, no OpenAlex, quantos registros cada família recupera. Só faz contagens.
- `data/`: snapshot, registros por versão, manifestos, amostra, triagem do LLM e pacotes de refinamento.

## Como rodar de novo

```bash
python3 scripts/coletar_arxiv.py --inicio 2021-01 --fim 2026-11      # cerca de 15 a 60 min
python3 scripts/aplicar_strings.py data/raw/arxiv/cs.SE_2021-01_2026-11.jsonl
python3 scripts/relatorio.py data/raw/arxiv/cs.SE_2021-01_2026-11.jsonl --n 15
python3 scripts/ablacao.py data/raw/arxiv/cs.SE_2021-01_2026-11.jsonl
python3 scripts/refinamento.py data/amostra/triagem_llm_q1.csv \
    --snapshot data/raw/arxiv/cs.SE_2021-01_2026-11.jsonl --candidato config/proposta_q2.yaml
python3 scripts/contar_openalex.py --config config/proposta_q2.yaml --filtro primary_topic.field.id:17
```

## Observações

- A API do arXiv aplica stemming e ignora o curinga. Por isso, o script baixa a categoria inteira e aplica as strings localmente.
- O OpenAlex foi consultado sem chave e sem e-mail. As contagens são estimativas: a base aplica stemming e não aceita curinga.
- `data/amostra/triagem_llm_q1.csv` foi triada pelo Claude Opus 5.5 em 17/11/2026, em uma rodada, por título e resumo. A conferência humana ainda não foi feita.
- A proposta de versão 2 só passa a valer depois de aprovada pela equipe. Antes de usá-la nas coletas, ela deve ser renomeada como versão oficial.
