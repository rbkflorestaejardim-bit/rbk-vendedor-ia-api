# RBK Vendedor IA API v0.11.2

O endpoint `/olist/produtos/pesquisar` recebeu o parâmetro
`consultar_estoque=false`.

Nesse modo, a pesquisa usa o catálogo local sincronizado e não realiza várias
chamadas de estoque à Olist. O modo administrativo continua consultando
estoque por padrão.

Não há migração SQL nesta versão.
