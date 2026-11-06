"""Erros de domínio tipados."""


class DomainError(Exception):
    """Erro base do domínio."""


class InvalidStateTransition(DomainError):
    """Transição de estado não permitida."""


class OrderNotCancelable(DomainError):
    """Pedido não está em um estado cancelável."""


class InvariantViolation(DomainError):
    """Violação de uma invariante de negócio."""
