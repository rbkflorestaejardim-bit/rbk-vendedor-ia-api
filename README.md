# RBK Vendedor IA API v0.9.0

A pesquisa deixa de depender das limitações da busca remota por `nome` em
cada atendimento. A API sincroniza todos os produtos ativos do Olist em um
catálogo local no PostgreSQL e pesquisa por palavras e números diretamente
nas descrições.

## Fluxo

1. `POST /olist/catalogo/sincronizar`
2. A API pagina `GET /produtos` sem filtro de nome.
3. Todos os produtos ativos são gravados localmente.
4. `GET /olist/produtos/pesquisar` consulta o catálogo local.
5. Apenas os produtos compatíveis recebem consulta de estoque em tempo real.
6. Entre os compatíveis, preço e estoque determinam a ordem comercial.

## Endpoints novos

- `POST /olist/catalogo/sincronizar`
- `GET /olist/catalogo/status`
- `GET /olist/catalogo/produto/{codigo}`

## Resultado esperado

Para `carburador + Stihl + MS 170`, o catálogo deve localizar tanto:

- SKU 12933 — CARBURADOR PARA MOTOSSERRA STIHL MS 170/180
- SKU 2452 — CARBURADOR ST-170 NOVA 2MIX

O SKU 12933 deve vir primeiro quando mantiver preço e estoque disponíveis.
