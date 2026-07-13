from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.probe_vision_pipeline import ProbeResult, load_probe_config, main


def test_probe_loads_dotenv_without_overriding_environment(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "SERPAPI_API_KEY=file-serp-secret\n"
        "VISION_MODEL_API_BASE=https://model.test/v1\n"
        "VISION_MODEL_API_KEY=file-model-secret\n"
        "VISION_MODEL_NAME=qwen-test\n",
        encoding="utf-8",
    )

    config = load_probe_config(
        {"SERPAPI_API_KEY": "env-serp-secret"},
        dotenv_path=dotenv,
    )

    assert config.serpapi_api_key == "env-serp-secret"
    assert config.vision_model_api_key == "file-model-secret"


@pytest.mark.parametrize("mode", ["lens-only", "full"])
def test_probe_prints_only_sanitized_summary(mode: str, capsys) -> None:
    secret = "provider-secret"

    async def runner(config, selected_mode: str, image_url: str) -> ProbeResult:
        assert selected_mode == mode
        assert image_url.endswith("token=private")
        return ProbeResult(
            mode=selected_mode,
            ok=True,
            duration_ms=1234,
            visual_matches=3,
            related_content=2,
            confidence="confirmed",
            identity=(
                f"Priestess {secret} https://private.test/a?token=x "
                "data:image/png;base64,AAAA"
            ),
            work_or_affiliation="Arknights",
            exact_fallbacks=1,
            web_fallbacks=0,
        )

    flag = "--lens-only" if mode == "lens-only" else "--full"
    code = main(
        [flag, "--image-url", "https://qq.test/image?token=private"],
        environ={
            "SERPAPI_API_KEY": secret,
            "VISION_MODEL_API_BASE": "https://model.test/v1",
            "VISION_MODEL_API_KEY": "model-secret",
            "VISION_MODEL_NAME": "qwen-test",
        },
        runner=runner,
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert code == 0
    assert payload["status"] == "ok"
    assert payload["duration_ms"] == 1234
    assert payload["visual_matches"] == 3
    assert payload["identity"] == "Priestess [redacted] [url] [data]"
    assert secret not in output
    assert "model-secret" not in output
    assert "token=private" not in output
    assert "base64" not in output


@pytest.mark.parametrize("error_type", ["dns", "tls", "authentication", "timeout", "malformed"])
def test_probe_returns_nonzero_for_provider_failures(error_type: str, capsys) -> None:
    async def runner(config, selected_mode: str, image_url: str) -> ProbeResult:
        return ProbeResult(mode=selected_mode, ok=False, error_type=error_type)

    code = main(
        ["--lens-only", "--image-url", "https://public.test/image.jpg"],
        environ={"SERPAPI_API_KEY": "secret"},
        runner=runner,
    )

    assert code == 1
    assert json.loads(capsys.readouterr().out)["error_type"] == error_type
