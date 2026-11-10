"""Infraestrutura compartilhada entre cenários (causa raiz da lentidão do eval).

`_run_all` cria UMA `SharedInfra` (engine, embedder, retriever) via `build_shared_infra()` e a
repassa a `build_real_deps(..., shared=...)`; loja, tokens, idempotência e checkpoint seguem
isolados por cenário. O engine compartilhado recebe `dispose()` uma vez ao final, mesmo com erro.
Sem Postgres nem modelo de embedding reais: as construções são substituídas por contadores.
"""

from pathlib import Path
from typing import Any

import pytest

from tests.fakes.scripted_llm import ScriptedLLM
from tests.fakes.shared_infra import Counts, FakeEngine
from tests.fakes.traces import scenario, trace, turn

pytestmark = pytest.mark.unit


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, infra: Counts):  # type: ignore[no-untyped-def]
    """CLI com provider falso e `run_scenario` que só registra as deps recebidas."""
    from evals import __main__ as cli

    from commerce_agents.infrastructure.llm import openai_compatible

    async def fake_run_scenario(sc: Any, deps: Any) -> Any:
        infra.deps.append(deps)
        if sc.id == "BOOM":
            raise RuntimeError("cenário explodiu")
        return trace(sc.id, turns=[turn()])

    monkeypatch.setattr(openai_compatible, "build_provider_from_env", lambda env: ScriptedLLM([]))
    monkeypatch.setattr(cli, "run_scenario", fake_run_scenario)
    return cli


def _scenarios(n: int) -> list[Any]:
    return [scenario(scenario_id=f"S-{i}") for i in range(n)]


# ------------------------------------------------------------------- uma vez por _run_all


async def test_run_all_cria_engine_embedder_e_retriever_uma_vez_para_cinco_cenarios(
    cli: Any, infra: Counts
):
    traces = await cli._run_all(_scenarios(5), {"LLM_MODEL": "m"}, 5)

    assert sorted(traces) == [f"S-{i}" for i in range(5)]
    assert infra.engines == 1
    assert infra.embedders == 1
    assert infra.retrievers == 1


async def test_run_all_descarta_o_engine_compartilhado_uma_vez(cli: Any, infra: Counts):
    await cli._run_all(_scenarios(5), {"LLM_MODEL": "m"}, 2)

    assert infra.disposed == 1


async def test_run_all_descarta_o_engine_mesmo_quando_um_cenario_levanta(cli: Any, infra: Counts):
    scenarios = [*_scenarios(2), scenario(scenario_id="BOOM")]

    with pytest.raises(RuntimeError):
        await cli._run_all(scenarios, {"LLM_MODEL": "m"}, 1)

    assert infra.engines == 1
    assert infra.disposed == 1


async def test_cenarios_do_mesmo_run_all_seguem_isolados(cli: Any, infra: Counts):
    await cli._run_all(_scenarios(2), {"LLM_MODEL": "m"}, 2)

    first, second = infra.deps
    assert first.tokens is not second.tokens
    assert first.idempotency is not second.idempotency
    assert first.tools is not second.tools
    assert first.reset.__self__ is not second.reset.__self__


async def test_reset_de_um_cenario_nao_afeta_a_loja_do_outro(cli: Any, infra: Counts):
    await cli._run_all(_scenarios(2), {"LLM_MODEL": "m"}, 2)
    first, second = infra.deps
    loja_do_segundo = second.reset.__self__
    antes = dict(vars(loja_do_segundo))

    first.reset()

    assert vars(loja_do_segundo) == antes


# ------------------------------------------------------------------ build_real_deps(shared=)


def test_build_real_deps_com_shared_nao_cria_engine_nem_embedder(infra: Counts):
    from evals.harness import SharedInfra, build_real_deps

    shared = SharedInfra(engine=FakeEngine(infra), embedder=object(), retriever=object())

    deps = build_real_deps(llm=ScriptedLLM([]), shared=shared)

    assert deps.tokens is not None
    assert (infra.engines, infra.embedders, infra.retrievers) == (0, 0, 0)


def test_build_shared_infra_cria_cada_peca_uma_vez(infra: Counts):
    from evals.harness import SharedInfra, build_shared_infra

    shared = build_shared_infra()

    assert isinstance(shared, SharedInfra)
    assert isinstance(shared.engine, FakeEngine)
    assert (infra.engines, infra.embedders, infra.retrievers) == (1, 1, 1)


def test_build_real_deps_sem_shared_mantem_o_comportamento_atual(infra: Counts):
    from evals.harness import build_real_deps

    build_real_deps(llm=ScriptedLLM([]))

    assert (infra.engines, infra.embedders, infra.retrievers) == (1, 1, 1)


# --------------------------------------------------------------------------- retry_infra


def test_reexecucao_cria_infra_por_run_all_e_nunca_por_cenario(
    cli: Any, infra: Counts, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """`main` com um cenário em erro de infra: 1 run_all inicial + 1 rodada de reexecução."""
    chamadas: dict[str, int] = {}

    async def flaky_run_scenario(sc: Any, deps: Any) -> Any:
        chamadas[sc.id] = chamadas.get(sc.id, 0) + 1
        if sc.id == "PED-001" and chamadas[sc.id] == 1:
            return trace(sc.id, infra_error="opencode indisponível")
        return trace(sc.id, turns=[turn()])

    monkeypatch.setattr(cli, "run_scenario", flaky_run_scenario)
    monkeypatch.setattr(cli, "RETRY_PAUSE_S", 0.0)
    monkeypatch.setattr(cli, "REPORTS_DIR", tmp_path)

    cli.main(["run", "--label", "fake", "--subset", "quick", "--retry-infra", "1"], environ={})

    assert chamadas["PED-001"] == 2
    assert 1 <= infra.engines <= 2
    assert infra.embedders == infra.engines
    assert infra.disposed == infra.engines
