import hmac
import os
import re
from contextlib import asynccontextmanager
from datetime import date, datetime, time
from typing import Any, Literal
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Security, status as http_status
from fastapi.security import APIKeyHeader
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator, model_validator


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
API_KEY = os.getenv("API_KEY", "").strip()

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Chave privada de acesso à API Comercial RBK.",
)

STATUS_AGENDA = {
    "pendente",
    "em_execucao",
    "concluida",
    "reagendada",
    "cancelada",
    "sem_resposta",
}


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
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A API ainda não possui chave de acesso configurada.",
        )

    if not chave_recebida or not hmac.compare_digest(chave_recebida, API_KEY):
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Chave de acesso inválida ou ausente.",
        )


def normalizar_documento(valor: str | None) -> str | None:
    if valor is None:
        return None
    documento = re.sub(r"\D", "", valor)
    return documento or None


def obter_vendedor_por_codigo(cursor, codigo: str) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT id, codigo, nome, ativo, uf_principal
        FROM comercial.vendedores_ia
        WHERE codigo = %s;
        """,
        (codigo.upper(),),
    )
    vendedor = cursor.fetchone()

    if vendedor is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Vendedor não encontrado.",
        )

    if not vendedor["ativo"]:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="O vendedor informado está inativo.",
        )

    return vendedor


def obter_cliente_por_id(cursor, cliente_id: UUID) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT
            c.*,
            v.codigo AS vendedor_codigo,
            v.nome_exibicao AS vendedor_nome
        FROM comercial.clientes c
        LEFT JOIN comercial.vendedores_ia v
            ON v.id = c.vendedor_id
        WHERE c.id = %s;
        """,
        (cliente_id,),
    )
    cliente = cursor.fetchone()

    if cliente is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Cliente não encontrado.",
        )

    return cliente


class ClienteCriar(BaseModel):
    crm_origem_id: str | None = Field(default=None, max_length=200)
    olist_id: str | None = Field(default=None, max_length=200)
    tipo_pessoa: Literal["CPF", "CNPJ"] | None = None
    cpf_cnpj: str | None = Field(default=None, max_length=20)
    razao_social: str | None = Field(default=None, max_length=200)
    nome_fantasia: str | None = Field(default=None, max_length=200)
    nome_contato: str | None = Field(default=None, max_length=150)
    telefone: str | None = Field(default=None, max_length=30)
    whatsapp: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=180)
    cidade: str | None = Field(default=None, max_length=120)
    uf: str | None = Field(default=None, min_length=2, max_length=2)
    vendedor_codigo: str | None = Field(default=None, max_length=40)
    status: str = Field(default="novo", max_length=40)
    origem: str = Field(default="crm_ligacoes", max_length=40)
    dados_adicionais: dict[str, Any] = Field(default_factory=dict)

    @field_validator("cpf_cnpj")
    @classmethod
    def validar_documento(cls, valor: str | None) -> str | None:
        return normalizar_documento(valor)

    @field_validator("uf")
    @classmethod
    def validar_uf(cls, valor: str | None) -> str | None:
        return valor.upper() if valor else None

    @field_validator("vendedor_codigo")
    @classmethod
    def validar_codigo_vendedor(cls, valor: str | None) -> str | None:
        return valor.upper() if valor else None

    @model_validator(mode="after")
    def validar_identificacao(self):
        if not any([self.razao_social, self.nome_fantasia, self.nome_contato]):
            raise ValueError(
                "Informe ao menos razão social, nome fantasia ou nome do contato."
            )
        return self


class ClienteAtualizar(BaseModel):
    crm_origem_id: str | None = Field(default=None, max_length=200)
    olist_id: str | None = Field(default=None, max_length=200)
    tipo_pessoa: Literal["CPF", "CNPJ"] | None = None
    cpf_cnpj: str | None = Field(default=None, max_length=20)
    razao_social: str | None = Field(default=None, max_length=200)
    nome_fantasia: str | None = Field(default=None, max_length=200)
    nome_contato: str | None = Field(default=None, max_length=150)
    telefone: str | None = Field(default=None, max_length=30)
    whatsapp: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=180)
    cidade: str | None = Field(default=None, max_length=120)
    uf: str | None = Field(default=None, min_length=2, max_length=2)
    vendedor_codigo: str | None = Field(default=None, max_length=40)
    status: str | None = Field(default=None, max_length=40)
    origem: str | None = Field(default=None, max_length=40)
    opt_out: bool | None = None
    bloqueado: bool | None = None
    proxima_acao_em: datetime | None = None
    dados_adicionais: dict[str, Any] | None = None

    @field_validator("cpf_cnpj")
    @classmethod
    def validar_documento(cls, valor: str | None) -> str | None:
        return normalizar_documento(valor)

    @field_validator("uf")
    @classmethod
    def validar_uf(cls, valor: str | None) -> str | None:
        return valor.upper() if valor else None

    @field_validator("vendedor_codigo")
    @classmethod
    def validar_codigo_vendedor(cls, valor: str | None) -> str | None:
        return valor.upper() if valor else None


class AgendaCriar(BaseModel):
    cliente_id: UUID
    vendedor_codigo: str = Field(max_length=40)
    data_agenda: date
    horario_previsto: time | None = None
    prioridade: int = Field(default=3, ge=1, le=5)
    objetivo: str | None = Field(default=None, max_length=255)
    canal_preferencial: Literal["telefone", "whatsapp", "email"] = "telefone"
    maximo_tentativas: int = Field(default=3, ge=1, le=10)
    observacao: str | None = None

    @field_validator("vendedor_codigo")
    @classmethod
    def validar_codigo_vendedor(cls, valor: str) -> str:
        return valor.upper()


class AgendaAtualizar(BaseModel):
    data_agenda: date | None = None
    horario_previsto: time | None = None
    prioridade: int | None = Field(default=None, ge=1, le=5)
    objetivo: str | None = Field(default=None, max_length=255)
    canal_preferencial: Literal["telefone", "whatsapp", "email"] | None = None
    status: Literal[
        "pendente",
        "em_execucao",
        "concluida",
        "reagendada",
        "cancelada",
        "sem_resposta",
    ] | None = None
    numero_tentativas: int | None = Field(default=None, ge=0, le=100)
    maximo_tentativas: int | None = Field(default=None, ge=1, le=10)
    ultima_tentativa_em: datetime | None = None
    proxima_tentativa_em: datetime | None = None
    resultado: str | None = Field(default=None, max_length=80)
    observacao: str | None = None


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
                    to_regclass('comercial.clientes') AS tabela_clientes,
                    to_regclass('comercial.agendas_comerciais') AS tabela_agendas,
                    to_regclass('comercial.configuracoes') AS tabela_configuracoes;
                """
            )
            resultado = cursor.fetchone()

            if resultado is None:
                raise RuntimeError(
                    "Não foi possível validar a estrutura do banco de dados."
                )

            tabelas = [
                resultado["tabela_vendedores"],
                resultado["tabela_clientes"],
                resultado["tabela_agendas"],
                resultado["tabela_configuracoes"],
            ]

            if any(tabela is None for tabela in tabelas):
                raise RuntimeError(
                    f"Estrutura comercial incompleta no banco {resultado['banco']}."
                )

    yield


app = FastAPI(
    title="RBK Vendedor IA API",
    description="API comercial do projeto piloto RBK Vendedor IA.",
    version="0.3.0",
    lifespan=lifespan,
)


@app.get("/saude", tags=["Sistema"])
def saude() -> dict[str, str]:
    return {
        "status": "ok",
        "servico": "api-comercial",
        "projeto": "RBK Vendedor IA",
        "versao": "0.3.0",
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
            status_code=http_status.HTTP_404_NOT_FOUND,
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
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Configuração não encontrada.",
        )

    return configuracao


@app.post(
    "/clientes",
    tags=["Clientes"],
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[Depends(validar_api_key)],
)
def criar_cliente(dados: ClienteCriar) -> dict[str, Any]:
    vendedor_id = None

    try:
        with obter_conexao() as conexao:
            with conexao.cursor() as cursor:
                if dados.vendedor_codigo:
                    vendedor = obter_vendedor_por_codigo(
                        cursor,
                        dados.vendedor_codigo,
                    )
                    vendedor_id = vendedor["id"]

                cursor.execute(
                    """
                    INSERT INTO comercial.clientes (
                        crm_origem_id,
                        olist_id,
                        tipo_pessoa,
                        cpf_cnpj,
                        razao_social,
                        nome_fantasia,
                        nome_contato,
                        telefone,
                        whatsapp,
                        email,
                        cidade,
                        uf,
                        vendedor_id,
                        status,
                        origem,
                        dados_adicionais
                    )
                    VALUES (
                        %(crm_origem_id)s,
                        %(olist_id)s,
                        %(tipo_pessoa)s,
                        %(cpf_cnpj)s,
                        %(razao_social)s,
                        %(nome_fantasia)s,
                        %(nome_contato)s,
                        %(telefone)s,
                        %(whatsapp)s,
                        %(email)s,
                        %(cidade)s,
                        %(uf)s,
                        %(vendedor_id)s,
                        %(status)s,
                        %(origem)s,
                        %(dados_adicionais)s
                    )
                    RETURNING id;
                    """,
                    {
                        **dados.model_dump(exclude={"vendedor_codigo", "dados_adicionais"}),
                        "vendedor_id": vendedor_id,
                        "dados_adicionais": Jsonb(dados.dados_adicionais),
                    },
                )
                cliente_id = cursor.fetchone()["id"]
                cliente = obter_cliente_por_id(cursor, cliente_id)

            conexao.commit()
            return cliente

    except UniqueViolation as erro:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Já existe um cliente com este CPF/CNPJ.",
        ) from erro


@app.get(
    "/clientes",
    tags=["Clientes"],
    dependencies=[Depends(validar_api_key)],
)
def listar_clientes(
    uf: str | None = Query(default=None, min_length=2, max_length=2),
    status_cliente: str | None = Query(default=None, alias="status"),
    vendedor_codigo: str | None = Query(default=None),
    limite: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    filtros = []
    parametros: list[Any] = []

    if uf:
        filtros.append("c.uf = %s")
        parametros.append(uf.upper())

    if status_cliente:
        filtros.append("c.status = %s")
        parametros.append(status_cliente)

    if vendedor_codigo:
        filtros.append("v.codigo = %s")
        parametros.append(vendedor_codigo.upper())

    where_sql = f"WHERE {' AND '.join(filtros)}" if filtros else ""

    consulta_total = f"""
        SELECT COUNT(*) AS total
        FROM comercial.clientes c
        LEFT JOIN comercial.vendedores_ia v
            ON v.id = c.vendedor_id
        {where_sql};
    """

    consulta_itens = f"""
        SELECT
            c.*,
            v.codigo AS vendedor_codigo,
            v.nome_exibicao AS vendedor_nome
        FROM comercial.clientes c
        LEFT JOIN comercial.vendedores_ia v
            ON v.id = c.vendedor_id
        {where_sql}
        ORDER BY c.criado_em DESC
        LIMIT %s OFFSET %s;
    """

    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(consulta_total, parametros)
            total = cursor.fetchone()["total"]

            cursor.execute(
                consulta_itens,
                [*parametros, limite, offset],
            )
            itens = cursor.fetchall()

    return {
        "total": total,
        "limite": limite,
        "offset": offset,
        "itens": itens,
    }


@app.get(
    "/clientes/{cliente_id}",
    tags=["Clientes"],
    dependencies=[Depends(validar_api_key)],
)
def buscar_cliente(cliente_id: UUID) -> dict[str, Any]:
    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            return obter_cliente_por_id(cursor, cliente_id)


@app.patch(
    "/clientes/{cliente_id}",
    tags=["Clientes"],
    dependencies=[Depends(validar_api_key)],
)
def atualizar_cliente(
    cliente_id: UUID,
    dados: ClienteAtualizar,
) -> dict[str, Any]:
    campos = dados.model_dump(exclude_unset=True)
    vendedor_codigo_informado = "vendedor_codigo" in campos
    vendedor_codigo = campos.pop("vendedor_codigo", None)

    if "dados_adicionais" in campos and campos["dados_adicionais"] is not None:
        campos["dados_adicionais"] = Jsonb(campos["dados_adicionais"])

    if not campos and not vendedor_codigo_informado:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Nenhum campo foi informado para atualização.",
        )

    try:
        with obter_conexao() as conexao:
            with conexao.cursor() as cursor:
                obter_cliente_por_id(cursor, cliente_id)

                if vendedor_codigo_informado:
                    if vendedor_codigo is None:
                        campos["vendedor_id"] = None
                    else:
                        vendedor = obter_vendedor_por_codigo(
                            cursor,
                            vendedor_codigo,
                        )
                        campos["vendedor_id"] = vendedor["id"]

                atribuicoes = [
                    f"{campo} = %s"
                    for campo in campos.keys()
                ]
                valores = list(campos.values())

                atribuicoes.append("atualizado_em = NOW()")

                cursor.execute(
                    f"""
                    UPDATE comercial.clientes
                    SET {", ".join(atribuicoes)}
                    WHERE id = %s;
                    """,
                    [*valores, cliente_id],
                )

                cliente = obter_cliente_por_id(cursor, cliente_id)

            conexao.commit()
            return cliente

    except UniqueViolation as erro:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Já existe um cliente com este CPF/CNPJ.",
        ) from erro


@app.post(
    "/agendas",
    tags=["Agenda"],
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[Depends(validar_api_key)],
)
def criar_agenda(dados: AgendaCriar) -> dict[str, Any]:
    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            cliente = obter_cliente_por_id(cursor, dados.cliente_id)
            vendedor = obter_vendedor_por_codigo(
                cursor,
                dados.vendedor_codigo,
            )

            if cliente["bloqueado"] or cliente["opt_out"]:
                raise HTTPException(
                    status_code=http_status.HTTP_409_CONFLICT,
                    detail="O cliente está bloqueado ou solicitou opt-out.",
                )

            cursor.execute(
                """
                INSERT INTO comercial.agendas_comerciais (
                    cliente_id,
                    vendedor_id,
                    data_agenda,
                    horario_previsto,
                    prioridade,
                    objetivo,
                    canal_preferencial,
                    maximo_tentativas,
                    observacao
                )
                VALUES (
                    %(cliente_id)s,
                    %(vendedor_id)s,
                    %(data_agenda)s,
                    %(horario_previsto)s,
                    %(prioridade)s,
                    %(objetivo)s,
                    %(canal_preferencial)s,
                    %(maximo_tentativas)s,
                    %(observacao)s
                )
                RETURNING id;
                """,
                {
                    **dados.model_dump(exclude={"vendedor_codigo"}),
                    "vendedor_id": vendedor["id"],
                },
            )
            agenda_id = cursor.fetchone()["id"]

            cursor.execute(
                """
                SELECT
                    a.*,
                    c.razao_social,
                    c.nome_fantasia,
                    c.nome_contato,
                    c.telefone,
                    c.whatsapp,
                    c.cidade,
                    c.uf,
                    v.codigo AS vendedor_codigo,
                    v.nome_exibicao AS vendedor_nome
                FROM comercial.agendas_comerciais a
                JOIN comercial.clientes c
                    ON c.id = a.cliente_id
                JOIN comercial.vendedores_ia v
                    ON v.id = a.vendedor_id
                WHERE a.id = %s;
                """,
                (agenda_id,),
            )
            agenda = cursor.fetchone()

        conexao.commit()
        return agenda


@app.get(
    "/agendas/proxima",
    tags=["Agenda"],
    dependencies=[Depends(validar_api_key)],
)
def buscar_proxima_agenda(
    vendedor_codigo: str,
    data_agenda: date | None = None,
) -> dict[str, Any]:
    data_consulta = data_agenda or date.today()

    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            vendedor = obter_vendedor_por_codigo(
                cursor,
                vendedor_codigo,
            )

            cursor.execute(
                """
                SELECT
                    a.*,
                    c.razao_social,
                    c.nome_fantasia,
                    c.nome_contato,
                    c.telefone,
                    c.whatsapp,
                    c.cidade,
                    c.uf,
                    c.cpf_cnpj,
                    c.dados_adicionais,
                    v.codigo AS vendedor_codigo,
                    v.nome_exibicao AS vendedor_nome
                FROM comercial.agendas_comerciais a
                JOIN comercial.clientes c
                    ON c.id = a.cliente_id
                JOIN comercial.vendedores_ia v
                    ON v.id = a.vendedor_id
                WHERE a.vendedor_id = %s
                  AND a.data_agenda = %s
                  AND a.status = 'pendente'
                  AND c.bloqueado = FALSE
                  AND c.opt_out = FALSE
                ORDER BY
                    a.prioridade ASC,
                    a.horario_previsto NULLS LAST,
                    a.criado_em ASC
                LIMIT 1;
                """,
                (vendedor["id"], data_consulta),
            )
            agenda = cursor.fetchone()

    if agenda is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Nenhuma agenda pendente encontrada para o vendedor e data informados.",
        )

    return agenda


@app.get(
    "/agendas",
    tags=["Agenda"],
    dependencies=[Depends(validar_api_key)],
)
def listar_agendas(
    data_agenda: date | None = None,
    vendedor_codigo: str | None = None,
    status_agenda: str | None = Query(default=None, alias="status"),
    limite: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    if status_agenda and status_agenda not in STATUS_AGENDA:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Status inválido. Use um destes: {', '.join(sorted(STATUS_AGENDA))}.",
        )

    filtros = []
    parametros: list[Any] = []

    if data_agenda:
        filtros.append("a.data_agenda = %s")
        parametros.append(data_agenda)

    if vendedor_codigo:
        filtros.append("v.codigo = %s")
        parametros.append(vendedor_codigo.upper())

    if status_agenda:
        filtros.append("a.status = %s")
        parametros.append(status_agenda)

    where_sql = f"WHERE {' AND '.join(filtros)}" if filtros else ""

    consulta_total = f"""
        SELECT COUNT(*) AS total
        FROM comercial.agendas_comerciais a
        JOIN comercial.vendedores_ia v
            ON v.id = a.vendedor_id
        {where_sql};
    """

    consulta_itens = f"""
        SELECT
            a.*,
            c.razao_social,
            c.nome_fantasia,
            c.nome_contato,
            c.telefone,
            c.whatsapp,
            c.cidade,
            c.uf,
            v.codigo AS vendedor_codigo,
            v.nome_exibicao AS vendedor_nome
        FROM comercial.agendas_comerciais a
        JOIN comercial.clientes c
            ON c.id = a.cliente_id
        JOIN comercial.vendedores_ia v
            ON v.id = a.vendedor_id
        {where_sql}
        ORDER BY
            a.data_agenda ASC,
            a.prioridade ASC,
            a.horario_previsto NULLS LAST,
            a.criado_em ASC
        LIMIT %s OFFSET %s;
    """

    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(consulta_total, parametros)
            total = cursor.fetchone()["total"]

            cursor.execute(
                consulta_itens,
                [*parametros, limite, offset],
            )
            itens = cursor.fetchall()

    return {
        "total": total,
        "limite": limite,
        "offset": offset,
        "itens": itens,
    }


@app.patch(
    "/agendas/{agenda_id}",
    tags=["Agenda"],
    dependencies=[Depends(validar_api_key)],
)
def atualizar_agenda(
    agenda_id: UUID,
    dados: AgendaAtualizar,
) -> dict[str, Any]:
    campos = dados.model_dump(exclude_unset=True)

    if not campos:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Nenhum campo foi informado para atualização.",
        )

    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM comercial.agendas_comerciais
                WHERE id = %s;
                """,
                (agenda_id,),
            )
            if cursor.fetchone() is None:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail="Agenda não encontrada.",
                )

            atribuicoes = [
                f"{campo} = %s"
                for campo in campos.keys()
            ]
            valores = list(campos.values())
            atribuicoes.append("atualizado_em = NOW()")

            cursor.execute(
                f"""
                UPDATE comercial.agendas_comerciais
                SET {", ".join(atribuicoes)}
                WHERE id = %s;
                """,
                [*valores, agenda_id],
            )

            cursor.execute(
                """
                SELECT
                    a.*,
                    c.razao_social,
                    c.nome_fantasia,
                    c.nome_contato,
                    c.telefone,
                    c.whatsapp,
                    c.cidade,
                    c.uf,
                    v.codigo AS vendedor_codigo,
                    v.nome_exibicao AS vendedor_nome
                FROM comercial.agendas_comerciais a
                JOIN comercial.clientes c
                    ON c.id = a.cliente_id
                JOIN comercial.vendedores_ia v
                    ON v.id = a.vendedor_id
                WHERE a.id = %s;
                """,
                (agenda_id,),
            )
            agenda = cursor.fetchone()

        conexao.commit()
        return agenda
