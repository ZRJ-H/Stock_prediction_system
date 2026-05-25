"""
LLM 调用服务（LLM Service）
===========================
封装 OpenAI 兼容 API 的调用逻辑，支持两种模式：
  1. 在线模式：配置 OPENAI_API_KEY 后，通过 HTTP 调用远程 LLM（支持 tool calling）
  2. 离线模式：API key 为空时，自动降级为本地规则引擎（由 agent.py 调度）

环境变量配置：
  - OPENAI_API_KEY  : API 密钥（必填，为空则离线）
  - OPENAI_BASE_URL : API 地址（默认 https://api.openai.com/v1）
  - OPENAI_MODEL    : 模型名称（默认 gpt-4o-mini）

兼容任意 OpenAI 格式的 API（DeepSeek、通义千问、vLLM 等）。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional


def build_prompt(result: Dict[str, float | str]) -> str:
    """根据预测结果构建发送给 LLM 的提示词。

    Args:
        result: 模型预测输出，含 label / confidence / prob_up / prob_down 等字段

    Returns:
        格式化的中文提示词字符串
    """
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
    """LLM 解释器，封装大模型调用与回落逻辑。

    核心职责：
      - explain(): 将模型预测结果转为自然语言解读
      - chat():    通用的多轮对话接口（支持 function calling / tool use）
      - 无 API key 时自动使用 _fallback_text() 模板生成解释
    """

    def __init__(self) -> None:
        # 从环境变量读取配置，缺失则使用默认值
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def _fallback_text(self, result: Dict[str, float | str]) -> str:
        """离线模式下的模板化解释生成（无需 LLM）。

        根据置信度和短期动量组合生成固定模板的解读文本。
        """
        direction = result["label"]
        confidence = float(result["confidence"]) * 100
        momentum = float(result["avg_return_5"])
        tone = "短线动能偏强" if momentum >= 0 else "短线动能偏弱"
        return (
            f"预测解释：模型判断下一时段更可能【{direction}】，置信度约 {confidence:.1f}%，{tone}。\n"
            "风险提示：该结果仅反映历史序列模式，不构成投资建议，需结合市场消息与仓位管理。"
        )

    def explain(self, result: Dict[str, float | str]) -> str:
        """对预测结果进行自然语言解释（在线优先，离线回退）。"""
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
        """通用 LLM 对话接口，支持 OpenAI function calling 协议。

        Args:
            messages: 对话消息列表，每条含 role + content
            tools:    可选的工具定义列表（OpenAI tool format）
            temperature: 生成温度，默认 0.4（偏确定性）

        Returns:
            成功 → {"role": "assistant", "content": "..."}  纯文本回复
            成功 → {"role": "assistant", "tool_calls": [...]} 工具调用请求
            失败 → None（调用方应回退到规则引擎）
        """
        if not self.api_key:
            return None

        # 构建请求体
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"  # 让 LLM 自行决定是否调用工具

        # 发送 HTTP POST 请求（不依赖第三方 SDK，减少依赖）
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

            # 解析 tool_calls（函数调用请求）
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
            # 网络异常或响应格式异常 → 返回 None 由调用方处理
            return None

    def _call_api(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.4,
    ) -> Optional[str]:
        """底层 API 调用：发送消息，返回纯文本回复（不使用 tool calling）。

        Returns:
            成功 → LLM 文本回复；失败 → None
        """
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
