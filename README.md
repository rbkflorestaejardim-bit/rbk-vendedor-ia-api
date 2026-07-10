# RBK Vendedor IA API

Versão `0.5.0`.

## Telefonia Twilio

Esta versão adiciona:

- Primeira chamada real pela Twilio;
- Template oficial de voz permitido na conta Trial;
- Consulta do estado da chamada;
- Webhook assinado para progresso da chamada;
- Auditoria dos eventos da Twilio.

## Novos endpoints

- `POST /telefonia/twilio/teste`
- `GET /telefonia/twilio/chamadas/{call_sid}`
- `POST /webhooks/twilio/status-chamada` (uso interno da Twilio)

## Variáveis obrigatórias

- `DATABASE_URL`
- `API_KEY`
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_PHONE_NUMBER`
- `TWILIO_BASE_URL`

## Observação do primeiro teste

O endpoint de teste utiliza o template oficial
`voice_text_to_speech` da Twilio. Depois que a chamada real for
validada, a próxima versão conectará o fluxo de voz próprio do vendedor IA.
