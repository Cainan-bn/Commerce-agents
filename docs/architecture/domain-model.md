# Modelo de domínio (contrato da Fase 03)

Camada `domain/`: **só biblioteca padrão** (dataclasses frozen, `enum`, `datetime`, `timedelta`). Sem Pydantic, SQLAlchemy ou I/O (import-linter impõe). Tempo sempre injetado (`now: datetime`, timezone-aware UTC); nunca `datetime.now()`. Entidades são imutáveis: operações retornam uma nova instância.

## Módulos e nomes (fixos; os testes importam exatamente destes caminhos)

| Módulo | Símbolos |
|---|---|
| `domain/shared/errors.py` | `DomainError(Exception)`, `InvalidStateTransition`, `OrderNotCancelable`, `InvariantViolation` (todas herdam de `DomainError`) |
| `domain/order/status.py` | `OrderStatus` (StrEnum), `ALLOWED_TRANSITIONS: Mapping[OrderStatus, frozenset[OrderStatus]]`, `can_transition(a, b) -> bool` |
| `domain/order/order.py` | `OrderItem(sku, qty, unit_price_cents)`, `Order`, `Order.is_cancelable`, `Order.transition_to(new, at)`, `Order.cancel(at)` |
| `domain/order/returns.py` | `RETURN_WINDOW = timedelta(days=7)`, `ReturnEligibilityReason` (StrEnum), `ReturnEligibility(eligible, reason, deadline)`, `ReturnRequest`, `evaluate_return_eligibility(order, sku, now, existing=())` |
| `domain/customer/customer.py` | `Customer(customer_id, name, email, phone, created_at)` |
| `domain/catalog/product.py` | `Variant(sku, size, color, stock)`, `Product`, `Product.variant(sku)`, `Variant.is_in_stock`, `Variant.can_fulfill(qty)` |
| `domain/conversation/conversation.py` | `ConversationStatus` (open, handoff, closed), `Message`, `Conversation`, `Conversation.record_inbound(message)`, `Conversation.request_handoff(reason, at)`, `Conversation.close(at)` |

## OrderStatus e transições

Valores: `pending_payment, paid, processing, shipped, in_transit, delivered, cancelled, return_requested, returned`.

```
pending_payment -> paid | cancelled
paid            -> processing | cancelled
processing      -> shipped | cancelled
shipped         -> in_transit
in_transit      -> delivered
delivered       -> return_requested
return_requested-> returned | delivered      (devolução recusada volta a delivered)
cancelled, returned: terminais
```
Qualquer outra transição lança `InvalidStateTransition`. Cancelável = `pending_payment | paid | processing` (igual ao mock_store e à política); `cancel(at)` fora desses lança `OrderNotCancelable`.

## Invariantes de `Order` (verificadas no construtor; violação lança `InvariantViolation`)
- pelo menos 1 item; `qty >= 1`; preços `>= 0`; `total_cents == sum(qty * unit_price_cents)`.
- `delivered_at` presente se e somente se status ∈ {`delivered`, `return_requested`, `returned`}.
- `tracking_code` obrigatório para `shipped, in_transit, delivered, return_requested, returned`.
- `delivered_at >= created_at`.
- `transition_to(delivered, at)` define `delivered_at = at`; `transition_to(shipped, ...)` exige `tracking_code` já presente (o código é atribuído por `with_tracking(code)`).

## Elegibilidade de troca/devolução (`evaluate_return_eligibility`)
Regra (idêntica ao mock_store): elegível se o pedido está `delivered`, o SKU pertence ao pedido, ainda não há solicitação aberta para esse SKU, e `now <= delivered_at + RETURN_WINDOW` (**limite inclusivo**). `deadline = delivered_at + RETURN_WINDOW`. Razões (`ReturnEligibilityReason`): `ok`, `not_delivered`, `deadline_exceeded`, `sku_not_in_order`, `already_requested`. Ordem de avaliação: `sku_not_in_order`, `not_delivered`, `already_requested`, `deadline_exceeded`. Para razões negativas que não dependem de prazo, `deadline` é `None` apenas quando `not_delivered`/`sku_not_in_order`.

## Conversation
- `record_inbound(message)` é idempotente por `message_id`: retorna `(conversation, is_new)`; duplicata devolve a mesma conversa e `is_new=False`; mantém ordem de chegada.
- Estados: `open -> handoff -> closed` e `open -> closed`; `handoff` não volta a `open`. Mensagem inbound em conversa `closed` lança `InvalidStateTransition`.
- `request_handoff(reason, at)`: só a partir de `open` (idempotente em `handoff`); reason não vazio.

## Persistência (infrastructure/persistence)
Tabelas derivadas dos dados da Fase 02 (`data/README.md`): `customers`, `products`, `product_variants`, `orders`, `order_items`, `return_requests`; mais `conversations` e `messages` (UNIQUE `message_id`). Valores monetários em centavos (`BIGINT`), timestamps `TIMESTAMPTZ`, `status` como `TEXT` com `CHECK` nos valores do enum. SQLAlchemy 2 async + Alembic. Repositórios implementam os ports de `application/ports/` (`OrderRepository`, `CatalogSearch`) e os novos `CustomerRepository` e `ConversationRepository` (assinaturas async, tipos de domínio no retorno; o CORE propõe e o Líder aprova antes do merge). `CatalogSearch.search` usa `tsvector` (dicionário `portuguese`) sobre nome, marca e categoria.
