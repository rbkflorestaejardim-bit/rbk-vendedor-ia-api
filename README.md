# RBK Vendedor IA API v0.11.1

## Correção do fluxo comercial

Itens que ficaram sem preço, não foram encontrados ou tiveram falha de
consulta durante uma conversa agora são agrupados em uma pendência comercial,
mesmo quando a chamada continua e outros produtos entram no orçamento.

A pendência é criada em `comercial.pendencias_comerciais` com o tipo:

```text
revisar_itens_catalogo
```

Não há migração SQL nesta versão.
