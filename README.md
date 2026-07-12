# RBK Vendedor IA API v0.10.1

## Ajustes na Gestão do Encarte

- prévia configurável de 3 a 12 produtos;
- produto com estoque zerado pode ser cadastrado e mantido no encarte;
- produto zerado não é oferecido pelo Carlos enquanto estiver indisponível;
- preço exibido exclusivamente a partir da Olist;
- preço bloqueado para edição na tela e nos endpoints;
- remoção definitiva da coluna `preco_encarte` por migração SQL.

## Tela fixa

```text
/encarte-admin
```

## Endpoint de ofertas

```text
GET /encarte/ofertas?quantidade=3..12
```

A oferta continua exigindo preço válido e estoque disponível. O cadastro do
encarte, entretanto, não exige estoque positivo.
