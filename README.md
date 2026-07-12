# RBK Vendedor IA API

Versão `0.7.0`.

## Persistência de conversas de voz

Esta versão preserva todos os endpoints da `0.6.0` e adiciona:

- `POST /chamadas/registrar-conversa-voz`

O endpoint recebe uma conversa concluída pelo `gateway-voz` e registra, em
uma única transação:

- chamada em `comercial.chamadas_ia`;
- cada fala do cliente em `comercial.interacoes`;
- cada resposta do vendedor IA em `comercial.interacoes`;
- resumo final da ligação;
- estado comercial e dados técnicos em `dados_extraidos`;
- snapshot da última triagem em `clientes.dados_adicionais`;
- auditoria em `comercial.acoes_agente`;
- conclusão da agenda, quando `agenda_id` for informado.

A operação é idempotente por `provedor + chamada_externa_id`. Execute antes
o arquivo SQL da Etapa 27 para criar o índice de proteção e o cliente
controlado do teste Linphone.
