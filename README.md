# RBK Vendedor IA API v0.12.1

A confirmação do carrinho cria uma proposta comercial interna para revisão.

Regras:

- não cria pedido automaticamente;
- vendedor padrão obrigatório: MARCIO;
- vendedor pesquisado na Olist por nome exato;
- cliente pesquisado exclusivamente por CPF/CNPJ;
- telefone, WhatsApp e e-mail não são usados para localizar cliente.

Endpoints:

- GET /olist/vendedores/padrao
- GET /propostas-comerciais
- GET /propostas-comerciais/{id}
- PATCH /propostas-comerciais/{id}/revisao

Variável:

OLIST_VENDEDOR_PADRAO_NOME=MARCIO
