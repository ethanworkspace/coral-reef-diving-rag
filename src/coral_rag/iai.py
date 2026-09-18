from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .settings import Settings


class IAIError(RuntimeError):
    pass


class IAIClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.api_key:
            raise IAIError("IAI_API_KEY is not set. Keep it in your local environment, never in this project.")
        self.settings = settings

    def _post(self, endpoint: str, payload: dict, rerank: bool = False) -> dict:
        headers = {"Content-Type": "application/json"}
        if rerank:
            headers["x-litellm-api-key"] = f"Bearer {self.settings.api_key}"
        else:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        request = Request(
            f"{self.settings.base_url}{endpoint}",
            data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise IAIError(f"iAI request failed ({exc.code}): {detail}") from exc
        except URLError as exc:
            raise IAIError(f"iAI connection failed: {exc.reason}") from exc

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._post("/v1/embeddings", {
            "model": self.settings.embedding_model, "input": texts, "encoding_format": "float"
        })
        data = sorted(response.get("data", []), key=lambda item: item.get("index", 0))
        vectors = [item["embedding"] for item in data]
        if len(vectors) != len(texts):
            raise IAIError("iAI embedding response did not contain one vector per input.")
        return vectors

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        response = self._post("/v1/rerank", {
            "model": self.settings.reranker_model, "query": query, "documents": documents, "top_n": top_n
        }, rerank=True)
        results = response.get("results", response.get("data", []))
        parsed = []
        for item in results:
            index = item.get("index")
            score = item.get("relevance_score", item.get("score", 0.0))
            if isinstance(index, int):
                parsed.append((index, float(score)))
        return sorted(parsed, key=lambda item: item[1], reverse=True)

    def chat(self, messages: list[dict[str, str]]) -> str:
        response = self._post("/v1/chat/completions", {
            "model": self.settings.chat_model, "messages": messages, "temperature": 0.1
        })
        try:
            return response["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise IAIError("iAI chat response did not contain a message.") from exc
