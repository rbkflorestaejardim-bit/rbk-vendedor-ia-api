# RBK Vendedor IA API

API comercial do projeto piloto.

## Versão

`0.2.0`

## Segurança

Os endpoints comerciais exigem o cabeçalho:

```text
X-API-Key: SUA_CHAVE
```

O endpoint `/saude` permanece público.

## Endpoints

- `GET /saude`
- `GET /vendedores`
- `GET /vendedores/CARLOS_RS`
- `GET /configuracoes/projeto`
- `GET /docs`

## Variáveis obrigatórias

- `DATABASE_URL`
- `API_KEY`

## Observação sobre senhas na DATABASE_URL

Caracteres especiais precisam ser codificados. Exemplo:

- `@` vira `%40`
- `#` vira `%23`
- `%` vira `%25`
