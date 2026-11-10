"""Todo teste sob tests/unit entra no gate `-m unit` (make test-unit e CI).

Sem isto, um arquivo que esquecesse `pytestmark = pytest.mark.unit` nunca rodava no gate: foi o
caso dos 161 testes de tests/unit/domain até a Fase 09.
"""

from pathlib import Path

import pytest

_UNIT_DIR = Path(__file__).parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # Hook de conftest recebe os itens da sessão inteira: filtra pelo diretório.
    for item in items:
        if item.path.is_relative_to(_UNIT_DIR) and item.get_closest_marker("unit") is None:
            item.add_marker(pytest.mark.unit)
