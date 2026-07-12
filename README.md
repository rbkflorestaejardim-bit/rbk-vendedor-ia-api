# RBK Vendedor IA API v0.8.0

Etapa 28A: conexão OAuth V3 com o Olist e pesquisa real de produtos.

## Endpoints novos

- `GET /olist/status`
- `POST /olist/oauth/iniciar`
- `GET /olist/oauth/callback`
- `GET /olist/produtos/pesquisar`

## Segurança

- Client ID e Client Secret permanecem nas variáveis do Easypanel.
- Access token e refresh token são criptografados no PostgreSQL com
  `pgcrypto`.
- O callback OAuth valida um `state` de uso único com validade de 15 minutos.
- A resposta pública de produtos não expõe preço de custo.

## Busca

A pesquisa usa combinações progressivas de:

- termo completo;
- peça + marca + modelo;
- peça + modelo;
- modelo;
- peça.

Os resultados são ranqueados localmente e os principais recebem consulta de
estoque no endpoint oficial `/estoque/{idProduto}`.

## Limite desta etapa

A API já consulta produto, preço de venda e estoque. O ramal 605 ainda não
chama essa pesquisa durante a ligação. Essa conexão será feita na Etapa 28B,
depois da validação manual do endpoint.
