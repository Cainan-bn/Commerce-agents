"""Respostas por template em pt-BR (ADR 0013). Nunca vêm do LLM e nunca expõem segredos."""

from commerce_agents.application.dto.confirmation import (
    ConfirmationOutcome,
    ConfirmationStatus,
    PendingAction,
)
from commerce_agents.application.dto.tools import ToolErrorCode


def clarification() -> str:
    return (
        "Não consegui entender bem o que você precisa. "
        "Pode me dizer, por exemplo, se é sobre um pedido, um produto, frete ou troca?"
    )


def refusal() -> str:
    return "Não posso ajudar com esse tipo de pedido. Posso ajudar com pedidos, produtos e trocas."


def handoff_notice() -> str:
    return "Vou encaminhar você para um atendente humano, que continuará daqui. Aguarde."


def llm_unavailable() -> str:
    return (
        "Estou com uma instabilidade no momento e não consegui processar seu pedido. "
        "Vou encaminhar você para um atendente humano."
    )


def no_source_found() -> str:
    return (
        "Não encontrei essa informação nas nossas políticas. "
        "Vou encaminhar você para um atendente humano confirmar."
    )


def identification_required() -> str:
    return (
        "Para consultar ou alterar pedidos preciso identificar você. Fale comigo pelo "
        "WhatsApp cadastrado na loja ou pelo site, já logado. Posso ajudar com produtos, "
        "frete e políticas por aqui."
    )


def handoff_waiting() -> str:
    return "Recebi sua mensagem. Um atendente humano já foi acionado e responderá por aqui."


_FAILURE_TEXTS: dict[ToolErrorCode, str] = {
    ToolErrorCode.NOT_CANCELABLE: "Esse pedido não pode mais ser cancelado.",
    ToolErrorCode.NOT_ELIGIBLE: "Esse item não é elegível para devolução.",
    ToolErrorCode.ALREADY_REQUESTED: "Essa solicitação já foi registrada antes.",
    ToolErrorCode.NOT_FOUND: "Não encontrei esse pedido na sua conta.",
}
_GENERIC_FAILURE = "Não consegui concluir a ação agora. Nada foi alterado; tente novamente depois."


def confirmation_outcome(outcome: ConfirmationOutcome, pending: PendingAction) -> str:
    """Texto do desfecho da confirmação. Usa só campos seguros da proposta (sem token/chave)."""
    order_id = pending.arguments.get("order_id", "")
    match outcome.status:
        case ConfirmationStatus.EXECUTED:
            if pending.tool_name == "cancel_order":
                return f"Pronto! O pedido {order_id} foi cancelado."
            return f"Pronto! Abri a solicitação de devolução do pedido {order_id}."
        case ConfirmationStatus.FAILED:
            error = outcome.error
            return _FAILURE_TEXTS.get(error.code, _GENERIC_FAILURE) if error else _GENERIC_FAILURE
        case ConfirmationStatus.DECLINED:
            return "Tudo bem, não vou fazer nenhuma alteração."
        case ConfirmationStatus.UNCLEAR:
            return f"Não entendi sua resposta. {pending.summary}"
        case ConfirmationStatus.EXPIRED:
            return "O tempo para confirmar acabou e nada foi alterado. Se quiser, peça de novo."
