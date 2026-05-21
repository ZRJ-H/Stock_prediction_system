from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional


def build_prompt(result: Dict[str, float | str]) -> str:
    return (
        "你是一个谨慎的股票分析助手，请基于模型输出给出简短解读。\n"
        f"预测方向: {result['label']}\n"
        f"置信度: {float(result['confidence']) * 100:.2f}%\n"
        f"上涨概率: {float(result['prob_up']) * 100:.2f}%\n"
        f"下跌概率: {float(result['prob_down']) * 100:.2f}%\n"
        f"最近收盘价: {float(result['latest_close']):.2f}\n"
        f"近5期平均涨跌幅: {float(result['avg_return_5']):.4f}%\n"
        f"近20期平均涨跌幅: {float(result['avg_return_20']):.4f}%\n"
        "请输出两段内容：1) 预测解释 2) 风险提示。每段不超过 80 字。"
    )


class LLMExplainer:
    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def _fallback_text(self, result: Dict[str, float | str]) -> str:
        direction = result["label"]
        confidence = float(result["confidence"]) * 100
        momentum = float(result["avg_return_5"])
        tone = "短线动能偏强" if momentum >= 0 else "短线动能偏弱"
        return (
            f"预测解释：模型判断下一时段更可能【{direction}】，置信度约 {confidence:.1f}%，{tone}。\n"
            "风险提示：该结果仅反映历史序列模式，不构成投资建议，需结合市场消息与仓位管理。"
        )

    def explain(self, result: Dict[str, float | str]) -> str:
        if not self.api_key:
            return self._fallback_text(result)
        messages = [
            {"role": "system", "content": "你是专业但保守的金融分析助手。"},
            {"role": "user", "content": build_prompt(result)},
        ]
        text = self._call_api(messages, temperature=0.4)
        if text is None:
            return self._fallback_text(result)
        return text.strip()

    def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[dict]] = None,
        temperature: float = 0.4,
    ) -> Optional[Dict[str, Any]]:
        """Call the LLM with optional tool definitions.

        Returns a dict with either:
          - {"role": "assistant", "content": "..."}
          - {"role": "assistant", "tool_calls": [{"name":..., "arguments":{...}}]}
        Or None if the call fails.
        """
        if not self.api_key:
            return None

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        req = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            choice = body["choices"][0]
            msg = choice["message"]
            result: Dict[str, Any] = {"role": "assistant"}

            if msg.get("tool_calls"):
                tc = msg["tool_calls"][0]
                func = tc.get("function", {})
                result["tool_calls"] = [{
                    "name": func.get("name", ""),
                    "arguments": json.loads(func.get("arguments", "{}")),
                }]
            elif msg.get("content"):
                result["content"] = msg["content"]
            else:
                result["content"] = ""
            return result
        except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError):
            return None

    def _call_api(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.4,
    ) -> Optional[str]:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        req = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
        except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError):
            return None
