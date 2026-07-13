# RBK Vendedor IA API v0.12.2

## Correção da localização do vendedor

A API agora reconhece o vendedor padrão por:

1. ID configurado;
2. código exato;
3. nome ou fantasia exatos;
4. nome compatível, como `MARCIO RUBIK`.

## Variáveis

```env
OLIST_VENDEDOR_PADRAO_NOME=MARCIO
OLIST_VENDEDOR_PADRAO_CODIGO=MARCIO
OLIST_VENDEDOR_PADRAO_ID=
```

O uso do ID é o método definitivo quando houver nomes semelhantes.

## Diagnóstico

```text
GET /olist/vendedores/diagnostico
GET /olist/vendedores/padrao
```

Não há migração SQL e não há alteração no gateway.
