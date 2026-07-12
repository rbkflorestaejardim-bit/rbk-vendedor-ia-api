import hmac
import os
import re
from contextlib import asynccontextmanager
from datetime import date, datetime, time
from zoneinfo import ZoneInfo
from typing import Any, Literal
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, Security, status as http_status
from fastapi.security import APIKeyHeader
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator, model_validator
from twilio.base.exceptions import TwilioRestException
from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import VoiceResponse


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
API_KEY = os.getenv("API_KEY", "").strip()
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "").strip()
TWILIO_BASE_URL = os.getenv("TWILIO_BASE_URL", "").strip().rstrip("/")

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

STATUS_CHAMADA = {
    "iniciada",
    "em_andamento",
    "concluida",
    "nao_atendida",
    "ocupado",
    "falha",
    "cancelada",
}

FUSO_PROJETO = ZoneInfo("America/Sao_Paulo")

STATUS_TWILIO_PARA_INTERNO = {
    "queued": "iniciada",
    "initiated": "iniciada",
    "ringing": "em_andamento",
    "in-progress": "em_andamento",
    "completed": "concluida",
    "busy": "ocupado",
    "failed": "falha",
    "no-answer": "nao_atendida",
    "canceled": "cancelada",
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


def obter_agenda_detalhada(cursor, agenda_id: UUID) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT
            a.*,
            c.cpf_cnpj,
            c.razao_social,
            c.nome_fantasia,
            c.nome_contato,
            c.telefone,
            c.whatsapp,
            c.email,
            c.cidade,
            c.uf,
            c.status AS cliente_status,
            c.opt_out,
            c.bloqueado,
            c.dados_adicionais,
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

    if agenda is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Agenda não encontrada.",
        )

    return agenda


def obter_chamada_detalhada(cursor, chamada_id: UUID) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT
            ch.*,
            a.data_agenda,
            a.status AS agenda_status,
            c.cpf_cnpj,
            c.razao_social,
            c.nome_fantasia,
            c.nome_contato,
            c.telefone,
            c.whatsapp,
            c.cidade,
            c.uf,
            v.codigo AS vendedor_codigo,
            v.nome_exibicao AS vendedor_nome
        FROM comercial.chamadas_ia ch
        LEFT JOIN comercial.agendas_comerciais a
            ON a.id = ch.agenda_id
        JOIN comercial.clientes c
            ON c.id = ch.cliente_id
        JOIN comercial.vendedores_ia v
            ON v.id = ch.vendedor_id
        WHERE ch.id = %s;
        """,
        (chamada_id,),
    )
    chamada = cursor.fetchone()

    if chamada is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Chamada não encontrada.",
        )

    return chamada


def validar_numero_e164(numero: str) -> str:
    numero_normalizado = numero.strip()

    if not re.fullmatch(r"\+[1-9]\d{7,14}", numero_normalizado):
        raise ValueError(
            "Use o número no formato internacional E.164, por exemplo +5541999999999."
        )

    return numero_normalizado


def mascarar_telefone(numero: str) -> str:
    if len(numero) <= 6:
        return "***"
    return f"{numero[:4]}{'*' * max(len(numero) - 8, 3)}{numero[-4:]}"


def obter_cliente_twilio() -> TwilioClient:
    return TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


async def validar_webhook_twilio(request: Request) -> dict[str, str]:
    assinatura = request.headers.get("X-Twilio-Signature", "")
    formulario = await request.form()
    dados = {str(chave): str(valor) for chave, valor in formulario.multi_items()}

    url_assinada = f"{TWILIO_BASE_URL}{request.url.path}"
    if request.url.query:
        url_assinada = f"{url_assinada}?{request.url.query}"

    validador = RequestValidator(TWILIO_AUTH_TOKEN)

    if not assinatura or not validador.validate(
        url_assinada,
        dados,
        assinatura,
    ):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Assinatura do webhook Twilio inválida.",
        )

    return dados


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


class AssumirProximaAgenda(BaseModel):
    vendedor_codigo: str = Field(max_length=40)
    data_agenda: date | None = None

    @field_validator("vendedor_codigo")
    @classmethod
    def validar_codigo_vendedor(cls, valor: str) -> str:
        return valor.upper()


class ChamadaIniciar(BaseModel):
    agenda_id: UUID
    provedor: str = Field(max_length=60)
    chamada_externa_id: str | None = Field(default=None, max_length=150)
    numero_origem: str | None = Field(default=None, max_length=30)
    numero_destino: str | None = Field(default=None, max_length=30)
    status: Literal["iniciada", "em_andamento"] = "iniciada"


class ChamadaFinalizar(BaseModel):
    status: Literal[
        "concluida",
        "nao_atendida",
        "ocupado",
        "falha",
        "cancelada",
    ]
    atendida: bool = False
    fim_em: datetime | None = None
    duracao_segundos: int | None = Field(default=None, ge=0)
    gravacao_url: str | None = None
    transcricao: str | None = None
    resumo: str | None = None
    sentimento: str | None = Field(default=None, max_length=40)
    intencao: str | None = Field(default=None, max_length=80)
    resultado: str | None = Field(default=None, max_length=80)
    custo_telefonia: float = Field(default=0, ge=0)
    custo_ia: float = Field(default=0, ge=0)
    dados_extraidos: dict[str, Any] = Field(default_factory=dict)
    agenda_status: Literal[
        "concluida",
        "reagendada",
        "cancelada",
        "sem_resposta",
    ]
    proxima_tentativa_em: datetime | None = None
    observacao_agenda: str | None = None
    cliente_status: str | None = Field(default=None, max_length=40)
    proxima_acao_em: datetime | None = None

    @model_validator(mode="after")
    def validar_reagendamento(self):
        if self.agenda_status == "reagendada" and self.proxima_tentativa_em is None:
            raise ValueError(
                "Informe proxima_tentativa_em quando a agenda for reagendada."
            )
        return self


class TurnoConversaVoz(BaseModel):
    numero: int = Field(ge=1, le=100)
    cliente: str = Field(min_length=1, max_length=5000)
    agente: str | None = Field(default=None, max_length=5000)


class ConversaVozRegistrar(BaseModel):
    cliente_id: UUID
    vendedor_codigo: str = Field(max_length=40)
    agenda_id: UUID | None = None
    provedor: str = Field(
        default="asterisk_audiosocket",
        max_length=60,
    )
    chamada_externa_id: str = Field(min_length=8, max_length=150)
    numero_origem: str | None = Field(default=None, max_length=30)
    numero_destino: str | None = Field(default=None, max_length=30)
    direcao: Literal["entrada", "saida"] = "saida"
    inicio_em: datetime
    fim_em: datetime
    duracao_segundos: int = Field(ge=0)
    resumo: str | None = Field(default=None, max_length=4000)
    sentimento: str | None = Field(default=None, max_length=40)
    intencao: str = Field(
        default="consulta_peca",
        max_length=80,
    )
    resultado: str = Field(max_length=80)
    levantamento_completo: bool = False
    motivo_encerramento: str | None = Field(
        default=None,
        max_length=200,
    )
    estado_comercial: dict[str, Any] = Field(default_factory=dict)
    turnos: list[TurnoConversaVoz] = Field(
        default_factory=list,
        max_length=20,
    )
    modelos: dict[str, Any] = Field(default_factory=dict)
    dados_extraidos: dict[str, Any] = Field(default_factory=dict)

    @field_validator("vendedor_codigo")
    @classmethod
    def validar_codigo_vendedor(cls, valor: str) -> str:
        return valor.upper()

    @model_validator(mode="after")
    def validar_periodo(self):
        if self.fim_em < self.inicio_em:
            raise ValueError(
                "fim_em não pode ser anterior a inicio_em."
            )
        return self


class TwilioTesteChamada(BaseModel):
    numero_destino: str = Field(
        description="Número verificado na Twilio, no padrão E.164.",
        examples=["+5541999999999"],
    )
    timeout_segundos: int = Field(default=25, ge=10, le=60)

    @field_validator("numero_destino")
    @classmethod
    def validar_destino(cls, valor: str) -> str:
        return validar_numero_e164(valor)


class TwilioTesteInterativo(BaseModel):
    numero_destino: str = Field(
        description="Número verificado na Twilio, no padrão E.164.",
        examples=["+5541999999999"],
    )
    timeout_segundos: int = Field(default=25, ge=10, le=60)

    @field_validator("numero_destino")
    @classmethod
    def validar_destino(cls, valor: str) -> str:
        return validar_numero_e164(valor)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DATABASE_URL:
        raise RuntimeError("A variável DATABASE_URL não foi configurada.")

    if not API_KEY:
        raise RuntimeError("A variável API_KEY não foi configurada.")

    variaveis_twilio = {
        "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
        "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
        "TWILIO_PHONE_NUMBER": TWILIO_PHONE_NUMBER,
        "TWILIO_BASE_URL": TWILIO_BASE_URL,
    }
    ausentes = [
        nome
        for nome, valor in variaveis_twilio.items()
        if not valor
    ]

    if ausentes:
        raise RuntimeError(
            "Variáveis Twilio não configuradas: " + ", ".join(ausentes)
        )

    if not TWILIO_ACCOUNT_SID.startswith("AC"):
        raise RuntimeError("TWILIO_ACCOUNT_SID inválido.")

    try:
        validar_numero_e164(TWILIO_PHONE_NUMBER)
    except ValueError as erro:
        raise RuntimeError("TWILIO_PHONE_NUMBER inválido.") from erro

    if not TWILIO_BASE_URL.startswith("https://"):
        raise RuntimeError("TWILIO_BASE_URL deve usar HTTPS.")

    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    current_database() AS banco,
                    to_regclass('comercial.vendedores_ia') AS tabela_vendedores,
                    to_regclass('comercial.clientes') AS tabela_clientes,
                    to_regclass('comercial.agendas_comerciais') AS tabela_agendas,
                    to_regclass('comercial.chamadas_ia') AS tabela_chamadas,
                    to_regclass('comercial.interacoes') AS tabela_interacoes,
                    to_regclass('comercial.acoes_agente') AS tabela_acoes,
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
                resultado["tabela_chamadas"],
                resultado["tabela_interacoes"],
                resultado["tabela_acoes"],
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
    version="0.7.0",
    lifespan=lifespan,
)


@app.get("/saude", tags=["Sistema"])
def saude() -> dict[str, str]:
    return {
        "status": "ok",
        "servico": "api-comercial",
        "projeto": "RBK Vendedor IA",
        "versao": "0.7.0",
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
    data_consulta = data_agenda or datetime.now(FUSO_PROJETO).date()

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


@app.post(
    "/agendas/assumir-proxima",
    tags=["Agenda"],
    dependencies=[Depends(validar_api_key)],
)
def assumir_proxima_agenda(
    dados: AssumirProximaAgenda,
) -> dict[str, Any]:
    data_consulta = dados.data_agenda or datetime.now(FUSO_PROJETO).date()

    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            vendedor = obter_vendedor_por_codigo(
                cursor,
                dados.vendedor_codigo,
            )

            cursor.execute(
                """
                SELECT a.id
                FROM comercial.agendas_comerciais a
                JOIN comercial.clientes c
                    ON c.id = a.cliente_id
                WHERE a.vendedor_id = %s
                  AND a.data_agenda = %s
                  AND a.status = 'pendente'
                  AND a.numero_tentativas < a.maximo_tentativas
                  AND c.bloqueado = FALSE
                  AND c.opt_out = FALSE
                ORDER BY
                    a.prioridade ASC,
                    a.horario_previsto NULLS LAST,
                    a.criado_em ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1;
                """,
                (vendedor["id"], data_consulta),
            )
            selecionada = cursor.fetchone()

            if selecionada is None:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail=(
                        "Nenhuma agenda pendente disponível para o vendedor "
                        "e data informados."
                    ),
                )

            agenda_id = selecionada["id"]

            cursor.execute(
                """
                UPDATE comercial.agendas_comerciais
                SET
                    status = 'em_execucao',
                    numero_tentativas = numero_tentativas + 1,
                    ultima_tentativa_em = NOW(),
                    atualizado_em = NOW()
                WHERE id = %s;
                """,
                (agenda_id,),
            )

            cursor.execute(
                """
                INSERT INTO comercial.acoes_agente (
                    vendedor_id,
                    cliente_id,
                    tipo_acao,
                    origem,
                    entrada,
                    saida,
                    sucesso
                )
                SELECT
                    a.vendedor_id,
                    a.cliente_id,
                    'assumir_agenda',
                    'api_comercial',
                    %s,
                    %s,
                    TRUE
                FROM comercial.agendas_comerciais a
                WHERE a.id = %s;
                """,
                (
                    Jsonb(
                        {
                            "vendedor_codigo": dados.vendedor_codigo,
                            "data_agenda": data_consulta.isoformat(),
                        }
                    ),
                    Jsonb(
                        {
                            "agenda_id": str(agenda_id),
                            "status": "em_execucao",
                        }
                    ),
                    agenda_id,
                ),
            )

            agenda = obter_agenda_detalhada(cursor, agenda_id)

        conexao.commit()
        return agenda


@app.post(
    "/agendas/{agenda_id}/liberar",
    tags=["Agenda"],
    dependencies=[Depends(validar_api_key)],
)
def liberar_agenda(
    agenda_id: UUID,
) -> dict[str, Any]:
    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            agenda = obter_agenda_detalhada(cursor, agenda_id)

            if agenda["status"] != "em_execucao":
                raise HTTPException(
                    status_code=http_status.HTTP_409_CONFLICT,
                    detail="Somente agendas em execução podem ser liberadas.",
                )

            cursor.execute(
                """
                UPDATE comercial.agendas_comerciais
                SET
                    status = 'pendente',
                    atualizado_em = NOW()
                WHERE id = %s;
                """,
                (agenda_id,),
            )

            cursor.execute(
                """
                INSERT INTO comercial.acoes_agente (
                    vendedor_id,
                    cliente_id,
                    tipo_acao,
                    origem,
                    entrada,
                    saida,
                    sucesso
                )
                VALUES (
                    %s,
                    %s,
                    'liberar_agenda',
                    'api_comercial',
                    %s,
                    %s,
                    TRUE
                );
                """,
                (
                    agenda["vendedor_id"],
                    agenda["cliente_id"],
                    Jsonb({"agenda_id": str(agenda_id)}),
                    Jsonb({"status": "pendente"}),
                ),
            )

            agenda_atualizada = obter_agenda_detalhada(cursor, agenda_id)

        conexao.commit()
        return agenda_atualizada


@app.post(
    "/chamadas",
    tags=["Chamadas"],
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[Depends(validar_api_key)],
)
def iniciar_chamada(
    dados: ChamadaIniciar,
) -> dict[str, Any]:
    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            agenda = obter_agenda_detalhada(cursor, dados.agenda_id)

            if agenda["status"] != "em_execucao":
                raise HTTPException(
                    status_code=http_status.HTTP_409_CONFLICT,
                    detail=(
                        "A agenda precisa estar em execução antes de iniciar "
                        "a chamada."
                    ),
                )

            numero_destino = dados.numero_destino or agenda["telefone"]

            if not numero_destino:
                raise HTTPException(
                    status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="O cliente não possui telefone para a chamada.",
                )

            cursor.execute(
                """
                INSERT INTO comercial.chamadas_ia (
                    agenda_id,
                    cliente_id,
                    vendedor_id,
                    provedor,
                    chamada_externa_id,
                    numero_origem,
                    numero_destino,
                    direcao,
                    status,
                    inicio_em
                )
                VALUES (
                    %(agenda_id)s,
                    %(cliente_id)s,
                    %(vendedor_id)s,
                    %(provedor)s,
                    %(chamada_externa_id)s,
                    %(numero_origem)s,
                    %(numero_destino)s,
                    'saida',
                    %(status)s,
                    NOW()
                )
                RETURNING id;
                """,
                {
                    "agenda_id": dados.agenda_id,
                    "cliente_id": agenda["cliente_id"],
                    "vendedor_id": agenda["vendedor_id"],
                    "provedor": dados.provedor,
                    "chamada_externa_id": dados.chamada_externa_id,
                    "numero_origem": dados.numero_origem,
                    "numero_destino": numero_destino,
                    "status": dados.status,
                },
            )
            chamada_id = cursor.fetchone()["id"]

            cursor.execute(
                """
                INSERT INTO comercial.acoes_agente (
                    vendedor_id,
                    cliente_id,
                    tipo_acao,
                    origem,
                    entrada,
                    saida,
                    sucesso
                )
                VALUES (
                    %s,
                    %s,
                    'iniciar_chamada',
                    'api_comercial',
                    %s,
                    %s,
                    TRUE
                );
                """,
                (
                    agenda["vendedor_id"],
                    agenda["cliente_id"],
                    Jsonb(
                        {
                            "agenda_id": str(dados.agenda_id),
                            "provedor": dados.provedor,
                            "numero_destino": numero_destino,
                        }
                    ),
                    Jsonb({"chamada_id": str(chamada_id)}),
                ),
            )

            chamada = obter_chamada_detalhada(cursor, chamada_id)

        conexao.commit()
        return chamada


@app.get(
    "/chamadas",
    tags=["Chamadas"],
    dependencies=[Depends(validar_api_key)],
)
def listar_chamadas(
    vendedor_codigo: str | None = None,
    cliente_id: UUID | None = None,
    status_chamada: str | None = Query(default=None, alias="status"),
    data_inicio: date | None = None,
    data_fim: date | None = None,
    limite: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    if status_chamada and status_chamada not in STATUS_CHAMADA:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Status inválido. Use um destes: {', '.join(sorted(STATUS_CHAMADA))}.",
        )

    filtros: list[str] = []
    parametros: list[Any] = []

    if vendedor_codigo:
        filtros.append("v.codigo = %s")
        parametros.append(vendedor_codigo.upper())

    if cliente_id:
        filtros.append("ch.cliente_id = %s")
        parametros.append(cliente_id)

    if status_chamada:
        filtros.append("ch.status = %s")
        parametros.append(status_chamada)

    if data_inicio:
        filtros.append("ch.criado_em::date >= %s")
        parametros.append(data_inicio)

    if data_fim:
        filtros.append("ch.criado_em::date <= %s")
        parametros.append(data_fim)

    where_sql = f"WHERE {' AND '.join(filtros)}" if filtros else ""

    consulta_total = f"""
        SELECT COUNT(*) AS total
        FROM comercial.chamadas_ia ch
        JOIN comercial.vendedores_ia v
            ON v.id = ch.vendedor_id
        {where_sql};
    """

    consulta_itens = f"""
        SELECT
            ch.*,
            a.data_agenda,
            a.status AS agenda_status,
            c.razao_social,
            c.nome_fantasia,
            c.nome_contato,
            c.telefone,
            c.cidade,
            c.uf,
            v.codigo AS vendedor_codigo,
            v.nome_exibicao AS vendedor_nome
        FROM comercial.chamadas_ia ch
        LEFT JOIN comercial.agendas_comerciais a
            ON a.id = ch.agenda_id
        JOIN comercial.clientes c
            ON c.id = ch.cliente_id
        JOIN comercial.vendedores_ia v
            ON v.id = ch.vendedor_id
        {where_sql}
        ORDER BY ch.criado_em DESC
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


def montar_resumo_conversa_voz(
    estado: dict[str, Any],
    levantamento_completo: bool,
    resultado: str,
) -> str:
    partes: list[str] = []

    campos = [
        ("Cliente", estado.get("nome_cliente")),
        ("Produto", estado.get("produto")),
        ("Marca", estado.get("marca_maquina")),
        ("Modelo", estado.get("modelo_maquina")),
        ("Quantidade", estado.get("quantidade")),
    ]

    for rotulo, valor in campos:
        if valor not in (None, "", [], {}):
            partes.append(f"{rotulo}: {valor}")

    dados_tecnicos = estado.get("dados_tecnicos")
    if isinstance(dados_tecnicos, dict) and dados_tecnicos:
        dados_formatados = ", ".join(
            f"{chave}: {valor}"
            for chave, valor in dados_tecnicos.items()
            if valor not in (None, "", [], {})
        )
        if dados_formatados:
            partes.append(f"Dados técnicos: {dados_formatados}")

    partes.append(
        "Levantamento técnico completo"
        if levantamento_completo
        else "Levantamento técnico incompleto"
    )
    partes.append(f"Resultado: {resultado}")

    return "; ".join(partes)[:4000]


@app.post(
    "/chamadas/registrar-conversa-voz",
    tags=["Chamadas"],
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[Depends(validar_api_key)],
)
def registrar_conversa_voz(
    dados: ConversaVozRegistrar,
) -> dict[str, Any]:
    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM comercial.chamadas_ia
                WHERE provedor = %s
                  AND chamada_externa_id = %s
                ORDER BY criado_em DESC
                LIMIT 1;
                """,
                (
                    dados.provedor,
                    dados.chamada_externa_id,
                ),
            )
            chamada_existente = cursor.fetchone()

            if chamada_existente is not None:
                return {
                    "criada": False,
                    "idempotente": True,
                    "interacoes_registradas": 0,
                    "chamada": obter_chamada_detalhada(
                        cursor,
                        chamada_existente["id"],
                    ),
                }

            vendedor = obter_vendedor_por_codigo(
                cursor,
                dados.vendedor_codigo,
            )
            cliente = obter_cliente_por_id(
                cursor,
                dados.cliente_id,
            )

            if (
                cliente["vendedor_id"] is not None
                and cliente["vendedor_id"] != vendedor["id"]
            ):
                raise HTTPException(
                    status_code=http_status.HTTP_409_CONFLICT,
                    detail=(
                        "O cliente está vinculado a outro vendedor. "
                        "Não foi possível registrar a conversa para "
                        f"{dados.vendedor_codigo}."
                    ),
                )

            agenda = None
            if dados.agenda_id is not None:
                agenda = obter_agenda_detalhada(
                    cursor,
                    dados.agenda_id,
                )

                if agenda["cliente_id"] != dados.cliente_id:
                    raise HTTPException(
                        status_code=http_status.HTTP_409_CONFLICT,
                        detail=(
                            "A agenda informada pertence a outro cliente."
                        ),
                    )

                if agenda["vendedor_id"] != vendedor["id"]:
                    raise HTTPException(
                        status_code=http_status.HTTP_409_CONFLICT,
                        detail=(
                            "A agenda informada pertence a outro vendedor."
                        ),
                    )

            transcricao_linhas: list[str] = []
            for turno in dados.turnos:
                transcricao_linhas.append(
                    f"Cliente: {turno.cliente.strip()}"
                )
                if turno.agente:
                    transcricao_linhas.append(
                        f"{vendedor['nome']}: {turno.agente.strip()}"
                    )

            transcricao_completa = "\n".join(transcricao_linhas)
            resumo = dados.resumo or montar_resumo_conversa_voz(
                dados.estado_comercial,
                dados.levantamento_completo,
                dados.resultado,
            )

            dados_extraidos = {
                **dados.dados_extraidos,
                "estado_comercial": dados.estado_comercial,
                "levantamento_completo": dados.levantamento_completo,
                "motivo_encerramento": dados.motivo_encerramento,
                "turnos": [
                    turno.model_dump()
                    for turno in dados.turnos
                ],
                "modelos": dados.modelos,
                "origem_integracao": "gateway_voz",
            }

            cursor.execute(
                """
                INSERT INTO comercial.chamadas_ia (
                    agenda_id,
                    cliente_id,
                    vendedor_id,
                    provedor,
                    chamada_externa_id,
                    numero_origem,
                    numero_destino,
                    direcao,
                    status,
                    inicio_em,
                    fim_em,
                    duracao_segundos,
                    atendida,
                    transcricao,
                    resumo,
                    sentimento,
                    intencao,
                    resultado,
                    custo_telefonia,
                    custo_ia,
                    custo_total,
                    dados_extraidos
                )
                VALUES (
                    %(agenda_id)s,
                    %(cliente_id)s,
                    %(vendedor_id)s,
                    %(provedor)s,
                    %(chamada_externa_id)s,
                    %(numero_origem)s,
                    %(numero_destino)s,
                    %(direcao)s,
                    'concluida',
                    %(inicio_em)s,
                    %(fim_em)s,
                    %(duracao_segundos)s,
                    TRUE,
                    %(transcricao)s,
                    %(resumo)s,
                    %(sentimento)s,
                    %(intencao)s,
                    %(resultado)s,
                    0,
                    0,
                    0,
                    %(dados_extraidos)s
                )
                RETURNING id;
                """,
                {
                    "agenda_id": dados.agenda_id,
                    "cliente_id": dados.cliente_id,
                    "vendedor_id": vendedor["id"],
                    "provedor": dados.provedor,
                    "chamada_externa_id": dados.chamada_externa_id,
                    "numero_origem": dados.numero_origem,
                    "numero_destino": dados.numero_destino,
                    "direcao": dados.direcao,
                    "inicio_em": dados.inicio_em,
                    "fim_em": dados.fim_em,
                    "duracao_segundos": dados.duracao_segundos,
                    "transcricao": transcricao_completa or None,
                    "resumo": resumo,
                    "sentimento": dados.sentimento,
                    "intencao": dados.intencao,
                    "resultado": dados.resultado,
                    "dados_extraidos": Jsonb(dados_extraidos),
                },
            )
            chamada_id = cursor.fetchone()["id"]

            interacoes_registradas = 0

            for turno in dados.turnos:
                cursor.execute(
                    """
                    INSERT INTO comercial.interacoes (
                        cliente_id,
                        vendedor_id,
                        canal,
                        direcao,
                        tipo,
                        mensagem,
                        intencao,
                        mensagem_externa_id
                    )
                    VALUES (
                        %s,
                        %s,
                        'telefone',
                        'entrada',
                        'fala_cliente_ia',
                        %s,
                        %s,
                        %s
                    );
                    """,
                    (
                        dados.cliente_id,
                        vendedor["id"],
                        turno.cliente,
                        dados.intencao,
                        (
                            f"{dados.chamada_externa_id}:"
                            f"cliente:{turno.numero}"
                        ),
                    ),
                )
                interacoes_registradas += 1

                if turno.agente:
                    cursor.execute(
                        """
                        INSERT INTO comercial.interacoes (
                            cliente_id,
                            vendedor_id,
                            canal,
                            direcao,
                            tipo,
                            mensagem,
                            intencao,
                            mensagem_externa_id
                        )
                        VALUES (
                            %s,
                            %s,
                            'telefone',
                            'saida',
                            'resposta_vendedor_ia',
                            %s,
                            %s,
                            %s
                        );
                        """,
                        (
                            dados.cliente_id,
                            vendedor["id"],
                            turno.agente,
                            dados.intencao,
                            (
                                f"{dados.chamada_externa_id}:"
                                f"agente:{turno.numero}"
                            ),
                        ),
                    )
                    interacoes_registradas += 1

            cursor.execute(
                """
                INSERT INTO comercial.interacoes (
                    cliente_id,
                    vendedor_id,
                    canal,
                    direcao,
                    tipo,
                    resumo,
                    intencao,
                    mensagem_externa_id
                )
                VALUES (
                    %s,
                    %s,
                    'telefone',
                    'saida',
                    'resumo_chamada_ia',
                    %s,
                    %s,
                    %s
                );
                """,
                (
                    dados.cliente_id,
                    vendedor["id"],
                    resumo,
                    dados.intencao,
                    f"{dados.chamada_externa_id}:resumo",
                ),
            )
            interacoes_registradas += 1

            snapshot_triagem = {
                "chamada_id": str(chamada_id),
                "chamada_externa_id": dados.chamada_externa_id,
                "vendedor_codigo": vendedor["codigo"],
                "resultado": dados.resultado,
                "levantamento_completo": dados.levantamento_completo,
                "estado_comercial": dados.estado_comercial,
                "resumo": resumo,
                "registrado_em": dados.fim_em.isoformat(),
            }

            cursor.execute(
                """
                UPDATE comercial.clientes
                SET
                    vendedor_id = COALESCE(vendedor_id, %s),
                    ultima_interacao_em = %s,
                    dados_adicionais = COALESCE(
                        dados_adicionais,
                        '{}'::jsonb
                    ) || jsonb_build_object(
                        'ultima_triagem_ia',
                        %s
                    ),
                    atualizado_em = NOW()
                WHERE id = %s;
                """,
                (
                    vendedor["id"],
                    dados.fim_em,
                    Jsonb(snapshot_triagem),
                    dados.cliente_id,
                ),
            )

            if agenda is not None:
                cursor.execute(
                    """
                    UPDATE comercial.agendas_comerciais
                    SET
                        status = 'concluida',
                        resultado = %s,
                        observacao = COALESCE(
                            NULLIF(observacao, ''),
                            %s
                        ),
                        atualizado_em = NOW()
                    WHERE id = %s;
                    """,
                    (
                        dados.resultado,
                        resumo,
                        dados.agenda_id,
                    ),
                )

            cursor.execute(
                """
                INSERT INTO comercial.acoes_agente (
                    vendedor_id,
                    cliente_id,
                    tipo_acao,
                    origem,
                    entrada,
                    saida,
                    sucesso,
                    duracao_ms
                )
                VALUES (
                    %s,
                    %s,
                    'registrar_conversa_voz',
                    'gateway_voz',
                    %s,
                    %s,
                    TRUE,
                    %s
                );
                """,
                (
                    vendedor["id"],
                    dados.cliente_id,
                    Jsonb(
                        {
                            "chamada_externa_id": (
                                dados.chamada_externa_id
                            ),
                            "agenda_id": (
                                str(dados.agenda_id)
                                if dados.agenda_id
                                else None
                            ),
                            "quantidade_turnos": len(dados.turnos),
                        }
                    ),
                    Jsonb(
                        {
                            "chamada_id": str(chamada_id),
                            "resultado": dados.resultado,
                            "levantamento_completo": (
                                dados.levantamento_completo
                            ),
                            "interacoes_registradas": (
                                interacoes_registradas
                            ),
                        }
                    ),
                    dados.duracao_segundos * 1000,
                ),
            )

            chamada = obter_chamada_detalhada(
                cursor,
                chamada_id,
            )

        conexao.commit()

    return {
        "criada": True,
        "idempotente": False,
        "interacoes_registradas": interacoes_registradas,
        "chamada": chamada,
    }


@app.get(
    "/chamadas/{chamada_id}",
    tags=["Chamadas"],
    dependencies=[Depends(validar_api_key)],
)
def buscar_chamada(
    chamada_id: UUID,
) -> dict[str, Any]:
    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            return obter_chamada_detalhada(cursor, chamada_id)


@app.patch(
    "/chamadas/{chamada_id}/finalizar",
    tags=["Chamadas"],
    dependencies=[Depends(validar_api_key)],
)
def finalizar_chamada(
    chamada_id: UUID,
    dados: ChamadaFinalizar,
) -> dict[str, Any]:
    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            chamada = obter_chamada_detalhada(cursor, chamada_id)

            if chamada["status"] in {
                "concluida",
                "nao_atendida",
                "ocupado",
                "falha",
                "cancelada",
            }:
                raise HTTPException(
                    status_code=http_status.HTTP_409_CONFLICT,
                    detail="Esta chamada já foi finalizada.",
                )

            fim_em = dados.fim_em or datetime.now(FUSO_PROJETO)
            custo_total = round(dados.custo_telefonia + dados.custo_ia, 4)

            cursor.execute(
                """
                UPDATE comercial.chamadas_ia
                SET
                    status = %(status)s,
                    atendida = %(atendida)s,
                    fim_em = %(fim_em)s,
                    duracao_segundos = %(duracao_segundos)s,
                    gravacao_url = %(gravacao_url)s,
                    transcricao = %(transcricao)s,
                    resumo = %(resumo)s,
                    sentimento = %(sentimento)s,
                    intencao = %(intencao)s,
                    resultado = %(resultado)s,
                    custo_telefonia = %(custo_telefonia)s,
                    custo_ia = %(custo_ia)s,
                    custo_total = %(custo_total)s,
                    dados_extraidos = %(dados_extraidos)s
                WHERE id = %(chamada_id)s;
                """,
                {
                    "status": dados.status,
                    "atendida": dados.atendida,
                    "fim_em": fim_em,
                    "duracao_segundos": dados.duracao_segundos,
                    "gravacao_url": dados.gravacao_url,
                    "transcricao": dados.transcricao,
                    "resumo": dados.resumo,
                    "sentimento": dados.sentimento,
                    "intencao": dados.intencao,
                    "resultado": dados.resultado,
                    "custo_telefonia": dados.custo_telefonia,
                    "custo_ia": dados.custo_ia,
                    "custo_total": custo_total,
                    "dados_extraidos": Jsonb(dados.dados_extraidos),
                    "chamada_id": chamada_id,
                },
            )

            cursor.execute(
                """
                UPDATE comercial.agendas_comerciais
                SET
                    status = %s,
                    resultado = %s,
                    proxima_tentativa_em = %s,
                    observacao = COALESCE(%s, observacao),
                    atualizado_em = NOW()
                WHERE id = %s;
                """,
                (
                    dados.agenda_status,
                    dados.resultado,
                    dados.proxima_tentativa_em,
                    dados.observacao_agenda,
                    chamada["agenda_id"],
                ),
            )

            cliente_atualizacoes = [
                "ultima_interacao_em = NOW()",
                "atualizado_em = NOW()",
            ]
            cliente_valores: list[Any] = []

            if dados.cliente_status is not None:
                cliente_atualizacoes.append("status = %s")
                cliente_valores.append(dados.cliente_status)

            if dados.proxima_acao_em is not None:
                cliente_atualizacoes.append("proxima_acao_em = %s")
                cliente_valores.append(dados.proxima_acao_em)

            cursor.execute(
                f"""
                UPDATE comercial.clientes
                SET {", ".join(cliente_atualizacoes)}
                WHERE id = %s;
                """,
                [*cliente_valores, chamada["cliente_id"]],
            )

            cursor.execute(
                """
                INSERT INTO comercial.interacoes (
                    cliente_id,
                    vendedor_id,
                    canal,
                    direcao,
                    tipo,
                    mensagem,
                    resumo,
                    intencao,
                    anexos
                )
                VALUES (
                    %s,
                    %s,
                    'telefone',
                    'saida',
                    'chamada_ia',
                    %s,
                    %s,
                    %s,
                    %s
                );
                """,
                (
                    chamada["cliente_id"],
                    chamada["vendedor_id"],
                    dados.transcricao,
                    dados.resumo,
                    dados.intencao,
                    Jsonb(
                        [
                            {
                                "tipo": "gravacao",
                                "url": dados.gravacao_url,
                            }
                        ]
                        if dados.gravacao_url
                        else []
                    ),
                ),
            )

            cursor.execute(
                """
                INSERT INTO comercial.acoes_agente (
                    vendedor_id,
                    cliente_id,
                    tipo_acao,
                    origem,
                    entrada,
                    saida,
                    sucesso,
                    custo
                )
                VALUES (
                    %s,
                    %s,
                    'finalizar_chamada',
                    'api_comercial',
                    %s,
                    %s,
                    TRUE,
                    %s
                );
                """,
                (
                    chamada["vendedor_id"],
                    chamada["cliente_id"],
                    Jsonb(
                        {
                            "chamada_id": str(chamada_id),
                            "agenda_status": dados.agenda_status,
                        }
                    ),
                    Jsonb(
                        {
                            "status": dados.status,
                            "atendida": dados.atendida,
                            "resultado": dados.resultado,
                        }
                    ),
                    custo_total,
                ),
            )

            chamada_finalizada = obter_chamada_detalhada(cursor, chamada_id)

        conexao.commit()
        return chamada_finalizada


@app.post(
    "/telefonia/twilio/teste",
    tags=["Telefonia Twilio"],
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[Depends(validar_api_key)],
)
def iniciar_teste_twilio(
    dados: TwilioTesteChamada,
) -> dict[str, Any]:
    template_trial = (
        "https://webhooks.twilio.com/v1/Voice/Template/"
        "voice_text_to_speech"
    )
    callback_url = f"{TWILIO_BASE_URL}/webhooks/twilio/status-chamada"
    telefone_mascarado = mascarar_telefone(dados.numero_destino)

    try:
        chamada = obter_cliente_twilio().calls.create(
            to=dados.numero_destino,
            from_=TWILIO_PHONE_NUMBER,
            url=template_trial,
            method="POST",
            status_callback=callback_url,
            status_callback_event=[
                "initiated",
                "ringing",
                "answered",
                "completed",
            ],
            status_callback_method="POST",
            timeout=dados.timeout_segundos,
        )
    except TwilioRestException as erro:
        with obter_conexao() as conexao:
            with conexao.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO comercial.acoes_agente (
                        tipo_acao,
                        origem,
                        entrada,
                        saida,
                        sucesso,
                        erro
                    )
                    VALUES (
                        'twilio_teste_chamada',
                        'api_comercial',
                        %s,
                        %s,
                        FALSE,
                        %s
                    );
                    """,
                    (
                        Jsonb(
                            {
                                "numero_destino": telefone_mascarado,
                                "timeout_segundos": dados.timeout_segundos,
                                "template": "voice_text_to_speech",
                            }
                        ),
                        Jsonb(
                            {
                                "codigo_twilio": erro.code,
                                "status_http": erro.status,
                            }
                        ),
                        str(erro),
                    ),
                )
            conexao.commit()

        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail={
                "mensagem": "A Twilio recusou a criação da chamada.",
                "codigo_twilio": erro.code,
                "status_http": erro.status,
                "detalhe_twilio": erro.msg,
            },
        ) from erro

    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO comercial.acoes_agente (
                    tipo_acao,
                    origem,
                    entrada,
                    saida,
                    sucesso
                )
                VALUES (
                    'twilio_teste_chamada',
                    'api_comercial',
                    %s,
                    %s,
                    TRUE
                );
                """,
                (
                    Jsonb(
                        {
                            "numero_destino": telefone_mascarado,
                            "timeout_segundos": dados.timeout_segundos,
                            "template": "voice_text_to_speech",
                        }
                    ),
                    Jsonb(
                        {
                            "call_sid": chamada.sid,
                            "status": chamada.status,
                            "numero_origem": TWILIO_PHONE_NUMBER,
                        }
                    ),
                ),
            )
        conexao.commit()

    return {
        "mensagem": "Chamada de teste solicitada à Twilio.",
        "call_sid": chamada.sid,
        "status": chamada.status,
        "numero_origem": TWILIO_PHONE_NUMBER,
        "numero_destino": telefone_mascarado,
        "template_trial": "voice_text_to_speech",
        "status_callback": callback_url,
    }


@app.get(
    "/telefonia/twilio/chamadas/{call_sid}",
    tags=["Telefonia Twilio"],
    dependencies=[Depends(validar_api_key)],
)
def consultar_chamada_twilio(
    call_sid: str,
) -> dict[str, Any]:
    if not re.fullmatch(r"CA[0-9a-fA-F]{32}", call_sid):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Call SID da Twilio inválido.",
        )

    try:
        chamada = obter_cliente_twilio().calls(call_sid).fetch()
    except TwilioRestException as erro:
        codigo_http = (
            http_status.HTTP_404_NOT_FOUND
            if erro.status == 404
            else http_status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=codigo_http,
            detail={
                "mensagem": "Não foi possível consultar a chamada na Twilio.",
                "codigo_twilio": erro.code,
                "status_http": erro.status,
                "detalhe_twilio": erro.msg,
            },
        ) from erro

    return {
        "call_sid": chamada.sid,
        "status": chamada.status,
        "direcao": chamada.direction,
        "numero_origem": chamada.from_,
        "numero_destino": mascarar_telefone(chamada.to),
        "duracao_segundos": chamada.duration,
        "preco": chamada.price,
        "moeda": chamada.price_unit,
        "inicio_em": chamada.start_time,
        "fim_em": chamada.end_time,
    }


@app.post(
    "/webhooks/twilio/status-chamada",
    include_in_schema=False,
)
async def receber_status_chamada_twilio(
    request: Request,
) -> dict[str, str]:
    dados = await validar_webhook_twilio(request)

    call_sid = dados.get("CallSid")
    status_twilio = dados.get("CallStatus", "")
    status_interno = STATUS_TWILIO_PARA_INTERNO.get(status_twilio)
    duracao = dados.get("CallDuration")

    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO comercial.acoes_agente (
                    tipo_acao,
                    origem,
                    entrada,
                    saida,
                    sucesso
                )
                VALUES (
                    'twilio_status_chamada',
                    'twilio_webhook',
                    %s,
                    %s,
                    TRUE
                );
                """,
                (
                    Jsonb(dados),
                    Jsonb(
                        {
                            "call_sid": call_sid,
                            "status_twilio": status_twilio,
                            "status_interno": status_interno,
                        }
                    ),
                ),
            )

            if call_sid and status_interno:
                cursor.execute(
                    """
                    UPDATE comercial.chamadas_ia
                    SET
                        status = %s,
                        duracao_segundos = COALESCE(%s, duracao_segundos),
                        atendida = CASE
                            WHEN %s IN ('em_andamento', 'concluida') THEN TRUE
                            ELSE atendida
                        END,
                        fim_em = CASE
                            WHEN %s IN (
                                'concluida',
                                'nao_atendida',
                                'ocupado',
                                'falha',
                                'cancelada'
                            )
                            THEN COALESCE(fim_em, NOW())
                            ELSE fim_em
                        END
                    WHERE chamada_externa_id = %s;
                    """,
                    (
                        status_interno,
                        int(duracao) if duracao and duracao.isdigit() else None,
                        status_interno,
                        status_interno,
                        call_sid,
                    ),
                )

        conexao.commit()

    return {"status": "recebido"}


@app.post(
    "/telefonia/twilio/teste-interativo",
    tags=["Telefonia Twilio"],
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[Depends(validar_api_key)],
)
def iniciar_teste_interativo_twilio(
    dados: TwilioTesteInterativo,
) -> dict[str, Any]:
    url_voz = f"{TWILIO_BASE_URL}/webhooks/twilio/voz-interativa"
    callback_url = f"{TWILIO_BASE_URL}/webhooks/twilio/status-chamada"
    telefone_mascarado = mascarar_telefone(dados.numero_destino)

    try:
        chamada = obter_cliente_twilio().calls.create(
            to=dados.numero_destino,
            from_=TWILIO_PHONE_NUMBER,
            url=url_voz,
            method="POST",
            status_callback=callback_url,
            status_callback_event=[
                "initiated",
                "ringing",
                "answered",
                "completed",
            ],
            status_callback_method="POST",
            timeout=dados.timeout_segundos,
        )
    except TwilioRestException as erro:
        with obter_conexao() as conexao:
            with conexao.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO comercial.acoes_agente (
                        tipo_acao,
                        origem,
                        entrada,
                        saida,
                        sucesso,
                        erro
                    )
                    VALUES (
                        'twilio_teste_interativo',
                        'api_comercial',
                        %s,
                        %s,
                        FALSE,
                        %s
                    );
                    """,
                    (
                        Jsonb(
                            {
                                "numero_destino": telefone_mascarado,
                                "timeout_segundos": dados.timeout_segundos,
                            }
                        ),
                        Jsonb(
                            {
                                "codigo_twilio": erro.code,
                                "status_http": erro.status,
                            }
                        ),
                        str(erro),
                    ),
                )
            conexao.commit()

        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail={
                "mensagem": "A Twilio recusou o teste interativo.",
                "codigo_twilio": erro.code,
                "status_http": erro.status,
                "detalhe_twilio": erro.msg,
            },
        ) from erro

    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO comercial.acoes_agente (
                    tipo_acao,
                    origem,
                    entrada,
                    saida,
                    sucesso
                )
                VALUES (
                    'twilio_teste_interativo',
                    'api_comercial',
                    %s,
                    %s,
                    TRUE
                );
                """,
                (
                    Jsonb(
                        {
                            "numero_destino": telefone_mascarado,
                            "timeout_segundos": dados.timeout_segundos,
                        }
                    ),
                    Jsonb(
                        {
                            "call_sid": chamada.sid,
                            "status": chamada.status,
                            "url_voz": url_voz,
                        }
                    ),
                ),
            )
        conexao.commit()

    return {
        "mensagem": "Teste interativo solicitado à Twilio.",
        "call_sid": chamada.sid,
        "status": chamada.status,
        "numero_origem": TWILIO_PHONE_NUMBER,
        "numero_destino": telefone_mascarado,
        "url_voz": url_voz,
        "status_callback": callback_url,
    }


@app.post(
    "/webhooks/twilio/voz-interativa",
    include_in_schema=False,
)
async def fornecer_voz_interativa_twilio(
    request: Request,
):
    await validar_webhook_twilio(request)

    resposta = VoiceResponse()
    coleta = resposta.gather(
        input="speech",
        action=f"{TWILIO_BASE_URL}/webhooks/twilio/resposta-interativa",
        method="POST",
        language="pt-BR",
        speech_timeout="auto",
        timeout=5,
        action_on_empty_result=True,
    )
    coleta.say(
        (
            "Olá. Aqui é o Carlos, assistente virtual da RBK Distribuidora. "
            "Esta é uma ligação de teste. "
            "Depois do sinal, diga seu nome e uma peça que gostaria de consultar."
        ),
        language="pt-BR",
    )
    resposta.say(
        "Não consegui receber sua resposta. O teste será encerrado.",
        language="pt-BR",
    )
    resposta.hangup()

    return Response(
        content=str(resposta),
        media_type="application/xml",
    )


@app.post(
    "/webhooks/twilio/resposta-interativa",
    include_in_schema=False,
)
async def receber_resposta_interativa_twilio(
    request: Request,
):
    dados = await validar_webhook_twilio(request)

    call_sid = dados.get("CallSid")
    fala = (dados.get("SpeechResult") or "").strip()
    confianca = dados.get("Confidence")

    if len(fala) > 500:
        fala = fala[:500]

    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO comercial.acoes_agente (
                    tipo_acao,
                    origem,
                    entrada,
                    saida,
                    sucesso
                )
                VALUES (
                    'twilio_resposta_interativa',
                    'twilio_webhook',
                    %s,
                    %s,
                    TRUE
                );
                """,
                (
                    Jsonb(
                        {
                            "CallSid": call_sid,
                            "SpeechResult": fala,
                            "Confidence": confianca,
                        }
                    ),
                    Jsonb(
                        {
                            "fala_recebida": bool(fala),
                            "tamanho": len(fala),
                        }
                    ),
                ),
            )
        conexao.commit()

    resposta = VoiceResponse()

    if fala:
        resposta.say(
            (
                "Entendi sua resposta. "
                "O reconhecimento de voz do projeto foi validado com sucesso. "
                "Obrigado."
            ),
            language="pt-BR",
        )
    else:
        resposta.say(
            (
                "Não consegui entender sua resposta. "
                "O teste de telefonia foi concluído, mas o reconhecimento "
                "de voz precisa ser repetido."
            ),
            language="pt-BR",
        )

    resposta.hangup()

    return Response(
        content=str(resposta),
        media_type="application/xml",
    )


@app.get(
    "/telefonia/twilio/teste-interativo/{call_sid}",
    tags=["Telefonia Twilio"],
    dependencies=[Depends(validar_api_key)],
)
def consultar_teste_interativo_twilio(
    call_sid: str,
) -> dict[str, Any]:
    if not re.fullmatch(r"CA[0-9a-fA-F]{32}", call_sid):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Call SID da Twilio inválido.",
        )

    with obter_conexao() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    entrada,
                    saida,
                    criado_em
                FROM comercial.acoes_agente
                WHERE tipo_acao = 'twilio_resposta_interativa'
                  AND entrada ->> 'CallSid' = %s
                ORDER BY criado_em DESC
                LIMIT 1;
                """,
                (call_sid,),
            )
            resultado = cursor.fetchone()

    if resultado is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Ainda não existe resposta reconhecida para esta chamada.",
        )

    return {
        "call_sid": call_sid,
        "fala_reconhecida": resultado["entrada"].get("SpeechResult"),
        "confianca": resultado["entrada"].get("Confidence"),
        "fala_recebida": resultado["saida"].get("fala_recebida"),
        "registrado_em": resultado["criado_em"],
    }

