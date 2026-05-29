from app.contracts.schemas import RequestContract, SourceContract, ToolResponseContract


def test_request_contract_normalizes_and_deduplicates_symbols() -> None:
    request = RequestContract.model_validate(
        {
            "library": "SKLearn",
            "symbols": ["openai.ChatCompletion.create", "openai.ChatCompletion.create", " another.Symbol "],
        }
    )

    assert request.library == "scikit-learn"
    assert request.symbols == ["openai.ChatCompletion.create", "another.Symbol"]


def test_source_contract_accepts_approved_urls() -> None:
    contract = SourceContract.model_validate(
        {
            "library": "openai",
            "official_docs": "https://docs.openai.com/",
            "github_repo": "https://github.com/openai/openai-python",
            "pypi_url": "https://pypi.org/pypi/openai/json",
            "latest_version": "1.52.0",
        }
    )

    assert contract.library == "openai"


def test_tool_response_contract_serializes() -> None:
    response = ToolResponseContract.model_validate(
        {
            "library": "openai",
            "latest_version": "1.52.0",
            "official_docs": "https://docs.openai.com/",
            "github_repo": "https://github.com/openai/openai-python",
            "pypi_url": "https://pypi.org/pypi/openai/json",
            "symbol_lifecycles": [],
            "release_history": [],
            "migration_guides": [],
        }
    )

    assert response.library == "openai"
