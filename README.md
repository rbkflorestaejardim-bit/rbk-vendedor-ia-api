# RBK Vendedor IA API v0.10.0

## Gestão do encarte

Nova tela administrativa:

```text
/encarte-admin
```

A tela permite:

- configurar nome e vigência do encarte;
- consultar produto pelo SKU no catálogo local da Olist;
- verificar preço e estoque;
- adicionar, editar, ativar, inativar ou excluir produtos;
- definir preço específico do encarte;
- definir prioridade comercial;
- visualizar uma prévia de 3 a 5 ofertas.

## Endpoint para o vendedor IA

```text
GET /encarte/ofertas?quantidade=5
```

O endpoint retorna somente produtos:

- pertencentes ao encarte vigente;
- ativos;
- com preço válido;
- com estoque disponível;
- ainda não excluídos da rodada de ofertas.

O parâmetro `excluir_skus` permite impedir repetição de produtos.

## Segurança

A página HTML é apenas a interface. Todas as consultas e alterações exigem
a chave `X-API-Key`. A chave digitada fica no `sessionStorage` da aba.
