import hmac
import os
import re
import json
import time as time_module
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, Security, status as http_status
from fastapi.encoders import jsonable_encoder
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


OLIST_API_BASE_URL = os.getenv(
    "OLIST_API_BASE_URL",
    "https://api.tiny.com.br/public-api/v3",
).strip().rstrip("/")
OLIST_AUTH_URL = os.getenv(
    "OLIST_AUTH_URL",
    "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/auth",
).strip()
OLIST_TOKEN_URL = os.getenv(
    "OLIST_TOKEN_URL",
    "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/token",
).strip()
OLIST_CLIENT_ID = os.getenv("OLIST_CLIENT_ID", "").strip()
OLIST_CLIENT_SECRET = os.getenv("OLIST_CLIENT_SECRET", "").strip()
OLIST_REDIRECT_URI = os.getenv("OLIST_REDIRECT_URI", "").strip()
OLIST_SCOPE = os.getenv("OLIST_SCOPE", "openid").strip() or "openid"
OLIST_TOKEN_CRYPTO_KEY = os.getenv(
    "OLIST_TOKEN_CRYPTO_KEY",
    "",
).strip()
OLIST_ID_LISTA_PRECO = os.getenv(
    "OLIST_ID_LISTA_PRECO",
    "",
).strip()
OLIST_TIMEOUT_SECONDS = int(
    os.getenv("OLIST_TIMEOUT_SECONDS", "25")
)

OLIST_VENDEDOR_PADRAO_NOME = os.getenv(
    "OLIST_VENDEDOR_PADRAO_NOME",
    "MARCIO",
).strip() or "MARCIO"
OLIST_VENDEDOR_PADRAO_CODIGO = os.getenv(
    "OLIST_VENDEDOR_PADRAO_CODIGO",
    "MARCIO",
).strip() or "MARCIO"
OLIST_VENDEDOR_PADRAO_ID = os.getenv(
    "OLIST_VENDEDOR_PADRAO_ID",
    "",
).strip()


ENCARTE_ADMIN_HTML = Path(__file__).with_name(
    "encarte_admin.html"
)

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
