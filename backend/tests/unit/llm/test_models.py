"""Tested-model registry and the one-request probe (ADR-0026). No network."""

from querycure.core.config import FREE_ROUTER, Settings
from querycure.llm.models import TESTED_STRUCTURED_MODELS, model_warning
from querycure.llm.probe import probe


def test_the_default_model_is_a_tested_structured_output_model() -> None:
    default = Settings.model_fields["llm_model"].default
    assert default in TESTED_STRUCTURED_MODELS
    assert model_warning(default) is None


def test_the_router_and_unknown_models_are_flagged() -> None:
    assert "1 valid structured output in 10" in (model_warning(FREE_ROUTER) or "")
    assert "probe" in (model_warning("some/new-model:free") or "")


async def test_probe_never_calls_a_provider_with_the_stub() -> None:
    settings = Settings(_env_file=None, LLM_PROVIDER="stub")  # type: ignore[call-arg]
    assert (await probe(settings, "stub/canned"))["status"] == "skipped"
