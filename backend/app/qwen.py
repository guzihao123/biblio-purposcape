"""OpenAI-compatible Qwen chat client for structured JSON responses."""

import json
import os

from app.recovery import retry_call

try:
    from openai import OpenAI
except ImportError:  # Keep fake/offline analysis usable before production deps install.
    OpenAI = None


class ChatModel:
    """Small synchronous Qwen adapter; credentials come only from the environment."""

    def __init__(self, client=None, model=None):
        self.model = model or os.environ.get('QWEN_MODEL') or 'qwen-plus'
        if client is not None:
            self._client = client
            return

        api_key = os.environ.get('QWEN_API_KEY')
        base_url = os.environ.get('QWEN_BASE_URL')
        if not api_key:
            raise RuntimeError('QWEN_API_KEY is required for Qwen analysis')
        if not base_url:
            raise RuntimeError('QWEN_BASE_URL is required for Qwen analysis')
        if OpenAI is None:
            raise RuntimeError('The openai package is required for live Qwen analysis')
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def complete_json(self, system_prompt, payload):
        """Request one JSON object/array and decode it without accepting prose."""

        response = retry_call(
            lambda: self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {
                        'role': 'user',
                        'content': json.dumps(payload, ensure_ascii=False),
                    },
                ],
                response_format={'type': 'json_object'},
                # Thinking mode costs ~9x latency on these strict JSON extraction calls.
                extra_body={'enable_thinking': False},
            ),
            attempts=3,
        )
        try:
            content = response.choices[0].message.content
            parsed = json.loads(content)
        except (AttributeError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise ValueError('Qwen response did not contain valid JSON') from error
        if not isinstance(parsed, (dict, list)):
            raise ValueError('Qwen response must be a valid JSON object or array')
        return parsed
