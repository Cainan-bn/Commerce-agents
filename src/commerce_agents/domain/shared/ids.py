"""Identificadores tipados compartilhados por todo o sistema."""

from typing import NewType

ConversationId = NewType("ConversationId", str)
MessageId = NewType("MessageId", str)
CustomerId = NewType("CustomerId", str)
OrderId = NewType("OrderId", str)
Sku = NewType("Sku", str)
IdempotencyKey = NewType("IdempotencyKey", str)
ConfirmationToken = NewType("ConfirmationToken", str)
