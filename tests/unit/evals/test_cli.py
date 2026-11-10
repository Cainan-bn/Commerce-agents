"""CLI de avaliação: subset quick fixo de 12 cenários e bloqueio do holdout dentro do repo."""

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data" / "eval_scenarios"

# 2 por categoria principal (pedidos, catalogo, politicas, pos_venda, ambiguo) + 2 de injection.
QUICK_IDS = [
    "PED-001",
    "IRR-001",
    "CAT-001",
    "CAT-002",
    "POL-001",
    "POL-003",
    "POS-001",
    "POS-006",
    "AMB-001",
    "AMB-002",
    "INJ-001",
    "INJ-002",
]


def _cli():  # type: ignore[no-untyped-def]
    from evals import __main__ as cli

    return cli


def test_subset_quick_tem_doze_ids_fixos_e_existentes():
    from evals.subsets import QUICK_SUBSET

    assert list(QUICK_SUBSET) == QUICK_IDS
    assert len(set(QUICK_SUBSET)) == 12


def test_todos_os_ids_do_quick_sao_do_split_dev():
    for scenario_id in QUICK_IDS:
        data = yaml.safe_load((DATA / f"{scenario_id}.yaml").read_text(encoding="utf-8"))
        assert data["split"] == "dev"


def test_holdout_recusado_sem_env_definido():
    with pytest.raises(SystemExit) as refused:
        _cli().main(["run", "--label", "x", "--split", "holdout"], environ={})

    assert refused.value.code != 0


def test_holdout_recusado_se_pasta_estiver_dentro_do_repo():
    with pytest.raises(SystemExit) as refused:
        _cli().main(
            ["run", "--label", "x", "--split", "holdout"],
            environ={"EVAL_HOLDOUT_DIR": str(REPO / "data")},
        )

    assert refused.value.code != 0


def test_holdout_aceito_com_pasta_fora_do_repo(tmp_path: Path):
    guard = _cli().check_split_allowed
    holdout = tmp_path / "holdout"
    holdout.mkdir()

    guard("holdout", environ={"EVAL_HOLDOUT_DIR": str(holdout)}, repo_root=REPO)


def test_dev_nao_precisa_de_holdout():
    _cli().check_split_allowed("dev", environ={}, repo_root=REPO)


def test_parser_aceita_subset_e_split():
    args = _cli().parse_args(["run", "--label", "base", "--subset", "quick", "--split", "dev"])

    assert args.label == "base"
    assert args.subset == "quick"
    assert args.split == "dev"
