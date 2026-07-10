import hmac
import os
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from psycopg.rows import dict_row


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
API_KEY = os.getenv("API_KEY", "").strip()

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Chave privada de acesso à API Comercial RBK.",
)


def obter_conexao():
    if not DATABASE_URL:
        raise RuntimeError("A variável DATABASE_URL não foi configurada.")

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=10,
    )


def validar_api_key(
    chave_recebida: str | None = Security(api_key_header),
) -> None:
    if not API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A API ainda não possui chave de acesso configurada.",
        )

    if not chave_recebida or not hmac.compare_digest(chave_recebida, API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chave de acesso inválida ou ausente.",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DATABASE_URL:
        raise RuntimeError("A variável DATABASE_URL não foi configurada.")

    if not API_KEY:
        raise RuntimeError("A variável API_KEY não foi configurada.")

    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    current_database() AS banco,
                    to_regclass('comercial.vendedores_ia') AS tabela_vendedores,
                    to_regclass('comercial.configuracoes') AS tabela_configuracoes;
                """
            )
            resultado = cursor.fetchone()

            if resultado is None:
                raise RuntimeError(
                    "Não foi possível validar a estrutura do banco de dados."
                )

            banco = resultado["banco"]
            tabela_vendedores = resultado["tabela_vendedores"]
            tabela_configuracoes = resultado["tabela_configuracoes"]

            if tabela_vendedores is None or tabela_configuracoes is None:
                raise RuntimeError(
                    f"Estrutura comercial não encontrada no banco {banco}."
                )

    yield


app = FastAPI(
    title="RBK Vendedor IA API",
    description="API comercial do projeto piloto RBK Vendedor IA.",
    version="0.2.1",
    lifespan=lifespan,
)


@app.get("/saude", tags=["Sistema"])
def saude() -> dict[str, str]:
    return {
        "status": "ok",
        "servico": "api-comercial",
        "projeto": "RBK Vendedor IA",
        "versao": "0.2.1",
    }


@app.get(
    "/vendedores",
    tags=["Vendedores"],
    dependencies=[Depends(validar_api_key)],
)
def listar_vendedores() -> list[dict[str, Any]]:
    consulta = """
        SELECT
            v.id,
            v.nome,
            v.nome_exibicao,
            v.codigo,
            v.ativo,
            v.uf_principal,
            v.meta_contatos_dia,
            v.tipo_telefonia,
            v.horario_inicio,
            v.horario_fim,
            v.timezone,
            COALESCE(
                jsonb_agg(
                    DISTINCT jsonb_build_object(
                        'uf', t.uf,
                        'ativo', t.ativo,
                        'cidades', t.cidades
                    )
                ) FILTER (WHERE t.id IS NOT NULL),
                '[]'::jsonb
            ) AS territorios
        FROM comercial.vendedores_ia v
        LEFT JOIN comercial.territorios_vendedor t
            ON t.vendedor_id = v.id
        GROUP BY v.id
        ORDER BY v.nome;
    """

    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(consulta)
            return cursor.fetchall()


@app.get(
    "/vendedores/{codigo}",
    tags=["Vendedores"],
    dependencies=[Depends(validar_api_key)],
)
def buscar_vendedor(codigo: str) -> dict[str, Any]:
    consulta = """
        SELECT
            v.id,
            v.nome,
            v.nome_exibicao,
            v.codigo,
            v.ativo,
            v.uf_principal,
            v.meta_contatos_dia,
            v.limite_chamadas_simultaneas,
            v.tipo_telefonia,
            v.horario_inicio,
            v.horario_fim,
            v.timezone,
            COALESCE(
                jsonb_agg(
                    DISTINCT jsonb_build_object(
                        'uf', t.uf,
                        'ativo', t.ativo,
                        'cidades', t.cidades
                    )
                ) FILTER (WHERE t.id IS NOT NULL),
                '[]'::jsonb
            ) AS territorios
        FROM comercial.vendedores_ia v
        LEFT JOIN comercial.territorios_vendedor t
            ON t.vendedor_id = v.id
        WHERE v.codigo = %s
        GROUP BY v.id;
    """

    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(consulta, (codigo.upper(),))
            vendedor = cursor.fetchone()

    if vendedor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendedor não encontrado.",
        )

    return vendedor


@app.get(
    "/configuracoes/{chave}",
    tags=["Configurações"],
    dependencies=[Depends(validar_api_key)],
)
def buscar_configuracao(chave: str) -> dict[str, Any]:
    consulta = """
        SELECT chave, valor, descricao, atualizado_em
        FROM comercial.configuracoes
        WHERE chave = %s;
    """

    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(consulta, (chave,))
            configuracao = cursor.fetchone()

    if configuracao is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Configuração não encontrada.",
        )

    return configuracao
