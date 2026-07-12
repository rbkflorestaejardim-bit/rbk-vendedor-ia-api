# RBK Vendedor IA API v0.10.2

## Regra comercial do encarte

Todo produto ativo cadastrado na tela do encarte pode ser ofertado pelo
Carlos desde que tenha preço de venda válido na Olist.

O estoque não bloqueia a oferta.

### Produto com estoque positivo

É apresentado como `pronta_entrega`.

### Produto com estoque zero ou consulta indisponível

É apresentado como `sob_consulta`. A mensagem sugerida informa que a
disponibilidade será verificada, sem prometer entrega imediata.

## Tela

```text
/encarte-admin
```

A prévia continua permitindo de 3 a 12 produtos.

## Endpoint

```text
GET /encarte/ofertas?quantidade=3..12
```

Cada oferta informa:

- preço da Olist;
- estoque consultado, quando disponível;
- `disponibilidade_comercial`;
- mensagem comercial sugerida;
- prioridade definida na tela.

Não há migração SQL nesta versão.
