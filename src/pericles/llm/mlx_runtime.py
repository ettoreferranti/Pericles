"""The real mlx-lm runtime (excluded from mutation; see the slow MLX contract test)."""

from __future__ import annotations

from typing import Any, cast

from pericles.llm.types import Sampling

Handle = tuple[Any, Any]  # (model, tokenizer)


class MlxLmRuntime:
    def __init__(self) -> None:
        import mlx.core as mx
        from mlx_lm import generate, load
        from mlx_lm.sample_utils import make_sampler

        self._mx: Any = mx
        self._load: Any = load
        self._generate: Any = generate
        self._make_sampler: Any = make_sampler

    def load(self, name: str) -> object:
        model, tokenizer = self._load(name)
        return (model, tokenizer)

    def chat_prompt(self, handle: object, messages: list[dict[str, str]]) -> str:
        _, tokenizer = cast(Handle, handle)
        return str(
            tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        )

    def count(self, handle: object, text: str) -> int:
        _, tokenizer = cast(Handle, handle)
        return len(tokenizer.encode(text))

    def generate(self, handle: object, prompt: str, sampling: Sampling, seed: int) -> str:
        model, tokenizer = cast(Handle, handle)
        self._mx.random.seed(seed)
        sampler = self._make_sampler(temp=sampling.temperature, top_p=sampling.top_p)
        return str(
            self._generate(
                model, tokenizer, prompt=prompt, max_tokens=sampling.max_tokens, sampler=sampler
            )
        )
