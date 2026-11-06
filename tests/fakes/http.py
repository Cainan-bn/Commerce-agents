"""Transporte HTTP de teste: registra requisições e injeta falhas nas primeiras tentativas."""

from __future__ import annotations

import httpx


class RecordingTransport(httpx.AsyncBaseTransport):
    """Encaminha ao transporte interno e registra cada requisição.

    As `timeout_first` primeiras tentativas levantam `httpx.ReadTimeout`; as `fail_first`
    seguintes devolvem `fail_status` sem chegar ao transporte interno.
    """

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        *,
        fail_first: int = 0,
        fail_status: int = 503,
        timeout_first: int = 0,
    ) -> None:
        self._inner = inner
        self._fail_first = fail_first
        self._fail_status = fail_status
        self._timeout_first = timeout_first
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        attempt = len(self.requests)
        if attempt <= self._timeout_first:
            raise httpx.ReadTimeout("timeout simulado", request=request)
        if attempt <= self._timeout_first + self._fail_first:
            return httpx.Response(
                self._fail_status, json={"detail": "falha injetada"}, request=request
            )
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()
