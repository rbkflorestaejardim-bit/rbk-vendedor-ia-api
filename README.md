# RBK Vendedor IA API v0.8.2

A pesquisa de produtos passa a seguir a lógica operacional do ERP Olist:
palavras e números são procurados na descrição, sem exigir a mesma ordem.

## Exemplo

Pesquisa:

```text
carburador stihl ms 170
```

Resultados compatíveis esperados:

```text
CARBURADOR PARA MOTOSSERRA STIHL MS 170/180
CARBURADOR ST-170 NOVA 2MIX
```

Produtos de modelos diferentes, como MS 461 ou MS 311, são descartados.

## Ordenação

A segurança da aplicação vem primeiro. Entre produtos compatíveis:

1. produto com preço e estoque disponível;
2. produto com preço, mas sem estoque;
3. produto com estoque, mas sem preço;
4. produto sem preço e sem estoque.

## Campos novos no retorno

- `situacao_comercial`;
- `prioridade_comercial`;
- `preco_disponivel`;
- `tem_estoque`;
- `modo_busca`;
- palavras e números encontrados;
- depósitos retornados pelo estoque.

## Observação

A API não utiliza `idListaPreco` como filtro automático, porque esse filtro
eliminaria produtos que ainda não possuem preço na lista. Esses produtos
devem continuar aparecendo depois das opções comercializáveis.
