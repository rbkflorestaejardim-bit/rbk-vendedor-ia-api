# RBK Vendedor IA API v0.9.2

Esta versão amplia a pesquisa do catálogo e cria uma fila real de vendas
futuras para revisão humana ou pelo futuro agente gerente.

## Busca flexível

A pesquisa não depende mais de marca e modelo. O termo completo pode conter:

- produto;
- material;
- cor;
- tipo;
- aplicação;
- características;
- números e referências.

Exemplos:

- cinto de sustentação para roçadeira universal laranja;
- luva de malha pigmentada branca;
- embreagem para MS 170.

As palavras adicionais do pedido passam a ser obrigatórias na descrição do
produto, enquanto marca e modelo continuam aceitando aliases como Stihl/ST.

## Venda futura

Quando a chamada termina sem venda imediata por falta de preço, estoque,
produto ou integração, a API cria automaticamente:

- uma oportunidade;
- uma pendência comercial;
- uma interação de sistema;
- uma próxima ação para retorno.

A fila pode ser consultada em:

- `GET /pendencias-comerciais`
- `PATCH /pendencias-comerciais/{id}`

O futuro agente gerente poderá consumir essa mesma fila.
