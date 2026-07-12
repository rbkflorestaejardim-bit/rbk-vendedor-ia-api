# RBK Vendedor IA API v0.11.0

## Etapa 31A — carrinho e orçamento de múltiplos itens

A API passa a manter um rascunho de orçamento durante a conversa do Carlos.

### Endpoints

```text
POST /orcamentos-ia/rascunho/itens
GET  /orcamentos-ia/rascunho/{chamada_externa_id}
POST /orcamentos-ia/rascunho/finalizar
```

Cada item é validado novamente no catálogo local da Olist. O preço não é
recebido do gateway: a API usa exclusivamente o preço atual sincronizado.

## Encarte

```text
GET /encarte/ofertas?quantidade=3..12
```

Produtos ativos do encarte com preço válido são retornados sem consulta de
estoque. O estoque não aparece na mensagem comercial e não bloqueia a oferta.

## Limite desta etapa

A confirmação deixa o orçamento interno com status `confirmado`. A criação
do orçamento real na Olist e o PDF serão ligados em uma etapa posterior.
