"""models.dev registry search ranking."""

from __future__ import annotations

from voidswitch.models.db import ModelsDevCache
from voidswitch.services import models_dev


def _rows() -> list[ModelsDevCache]:
    return [
        ModelsDevCache(
            id="openrouter",
            data={
                "name": "OpenRouter",
                "models": {"deepseek/deepseek-v4-pro": {"name": "DeepSeek V4 Pro"}},
            },
        ),
        ModelsDevCache(
            id="deepseek",
            data={"name": "DeepSeek", "models": {"deepseek-v4-pro": {"name": "DeepSeek V4 Pro"}}},
        ),
        ModelsDevCache(
            id="openai", data={"name": "OpenAI", "models": {"gpt-5": {"name": "GPT-5"}}}
        ),
    ]


def _ids(results: list[dict]) -> list[str]:
    return [f"{r['provider']}/{r['id']}" for r in results]


def test_search_prefers_official_exact_match():
    """Searching a bare model id leads with the provider's own listing, not an
    alphabetical third-party aggregate."""
    results = models_dev.search_models(_rows(), "deepseek-v4-pro")
    ids = _ids(results)
    assert ids[0] == "deepseek/deepseek-v4-pro"
    assert "openrouter/deepseek/deepseek-v4-pro" in ids[1:]


def test_search_full_id_exact_match_wins():
    results = models_dev.search_models(_rows(), "deepseek/deepseek-v4-pro")
    assert _ids(results)[0] == "deepseek/deepseek-v4-pro"


def test_search_prefix_and_substring_rank_below_exact():
    results = models_dev.search_models(_rows(), "deepseek")
    ids = _ids(results)
    # The provider id match still surfaces both listings.
    assert set(ids) == {"deepseek/deepseek-v4-pro", "openrouter/deepseek/deepseek-v4-pro"}


def test_search_no_match_is_empty():
    assert models_dev.search_models(_rows(), "claude") == []
