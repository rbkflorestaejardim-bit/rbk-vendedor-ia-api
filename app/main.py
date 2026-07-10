import os
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException
from psycopg.rows import dict_row


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def obter_conexao():
    if not DATABASE_URL:
        raise RuntimeError("A variável DATABASE_URL não foi configurada.")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DATABASE_URL:
        raise RuntimeError("A variável DATABASE_URL não foi configurada.")

    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute("SELECT 1;")
            cursor.fetchone()

    yield


app = FastAPI(
    title="RBK Vendedor IA API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/saude")
def saude() -> dict[str, str]:
    return {
        "status": "ok",
        "servico": "api-comercial",
        "projeto": "RBK Vendedor IA",
    }


@app.get("/vendedores")
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


@app.get("/vendedores/{codigo}")
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
        raise HTTPException(status_code=404, detail="Vendedor não encontrado.")

    return vendedor


@app.get("/configuracoes/{chave}")
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
        raise HTTPException(status_code=404, detail="Configuração não encontrada.")

    return configuracao
