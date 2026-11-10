"""Segredos fora dos logs de acesso (ADR 0013/0014).

O navegador não manda header no WebSocket, então o token da sessão web vai na query
(`/ws/web/<id>?token=...`), e a verificação do webhook da Meta traz `hub.verify_token`. O uvicorn
loga o caminho com a query inteira; este filtro troca o valor desses parâmetros por `***`.
"""

import logging
import re
from typing import Any

_SENSITIVE_QUERY = re.compile(
    r"(?<=[?&])(token|hub\.verify_token|access_token)=[^&\s\"'#]*", re.IGNORECASE
)
REDACTED = "***"


def redact_query_tokens(text: str) -> str:
    return _SENSITIVE_QUERY.sub(rf"\1={REDACTED}", text)


def _redact(value: Any) -> Any:
    return redact_query_tokens(value) if isinstance(value, str) else value


class RedactQueryTokens(logging.Filter):
    """Esconde `token`, `hub.verify_token` e `access_token` da query em `msg` e `args`.

    Nunca descarta a linha; só reescreve o valor dos parâmetros sensíveis.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: _redact(value) for key, value in record.args.items()}
        return True
