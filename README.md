# RBK Vendedor IA API v0.9.1

Correção do erro HTTP 500 na pesquisa do catálogo Olist.

## Causa

O resultado da pesquisa contém campos `datetime`, como:

- `catalogo_sincronizado_em`;
- `sincronizado_em` dos produtos.

O FastAPI consegue devolver esses valores na resposta HTTP, mas o adaptador
`Jsonb` do psycopg não serializa objetos `datetime` diretamente.

## Correção

Antes de gravar o histórico em `comercial.consultas_olist`, o resultado agora
é convertido com `fastapi.encoders.jsonable_encoder`.

Isso também protege a gravação contra UUID, Decimal, date e outros tipos
compatíveis com respostas FastAPI, mas não nativos do JSON.

Nenhuma alteração de SQL, gateway-voz, Asterisk ou PostgreSQL é necessária.
