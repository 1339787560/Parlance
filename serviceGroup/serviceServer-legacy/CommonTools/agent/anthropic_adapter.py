"""
Anthropic API 适配器 - 将 Anthropic SDK 调用转换为聚合平台 API 格式

该适配器允许使用 Anthropic 风格的接口与聚合平台通信。
聚合平台使用 OpenAI 兼容格式，本适配器负责格式转换。
"""

import time
from typing import Optional, List, Dict, Any, Generator, Callable, Union
from dataclasses import dataclass, field
from openai import OpenAI


@dataclass
class Message:
    """Anthropic 风格的消息对象"""
    role: str
    content: str


@dataclass
class ContentBlock:
    """内容块，用于流式响应"""
    type: str
    text: str = ""


@dataclass
class Usage:
    """Token 使用统计"""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class AnthropicResponse:
    """Anthropic 风格的响应对象"""
    id: str
    type: str = "message"
    role: str = "assistant"
    content: List[ContentBlock] = field(default_factory=list)
    model: str = ""
    stop_reason: Optional[str] = None
    usage: Usage = field(default_factory=Usage)

    def __iter__(self):
        return iter(self.content)


class AnthropicAdapter:
    """
    Anthropic API 适配器

    将 Anthropic SDK 风格的调用转换为聚合平台支持的 OpenAI 格式。

    使用示例:
        client = AnthropicAdapter(
            api_key="your-api-key",
            base_url="http://aiapi.tcy365.net:82"
        )

        # 非流式调用
        response = client.messages.create(
            model="glm-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": "你好"}]
        )

        # 流式调用
        with client.messages.stream(
            model="glm-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": "你好"}]
        ) as stream:
            for text in stream.text_stream:
                print(text, end="")
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "http://aiapi.tcy365.net:82",
        default_model: str = "glm-5"
    ):
        """
        初始化适配器

        Args:
            api_key: API 密钥
            base_url: 聚合平台基础 URL
            default_model: 默认使用的模型
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.default_model = default_model

        # 清洗 URL，确保格式正确
        cleaned_url = self.base_url
        if cleaned_url.endswith('/v1/messages'):
            cleaned_url = cleaned_url.replace('/v1/messages', '/v1')
        elif not cleaned_url.endswith('/v1'):
            cleaned_url = f"{cleaned_url}/v1"

        self._client = OpenAI(api_key=api_key, base_url=cleaned_url)
        self.messages = Messages(self)

    def _convert_messages(self, messages: List[Dict]) -> List[Dict]:
        """
        转换消息格式

        Anthropic 和 OpenAI 的消息格式基本兼容，
        但需要处理 system 消息的特殊情况。
        """
        converted = []
        system_content = None

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Anthropic 的 system 消息需要单独处理
            if role == "system":
                system_content = content
                continue

            converted.append({
                "role": role,
                "content": content
            })

        return converted, system_content

    def _create_response(
        self,
        model: str,
        messages: List[Dict],
        max_tokens: int = 1024,
        stream: bool = False,
        **kwargs
    ) -> Union[AnthropicResponse, Generator]:
        """
        创建响应

        Args:
            model: 模型名称
            messages: 消息列表
            max_tokens: 最大输出 token 数
            stream: 是否使用流式输出
            **kwargs: 其他参数
        """
        converted_messages, system_content = self._convert_messages(messages)

        # 如果有 system 消息，添加到开头
        if system_content:
            converted_messages.insert(0, {
                "role": "system",
                "content": system_content
            })

        request_params = {
            "model": model or self.default_model,
            "messages": converted_messages,
            "max_tokens": max_tokens,
            "stream": stream,
            **kwargs
        }

        if stream:
            return self._stream_response(request_params)
        else:
            return self._sync_response(request_params)

    def _sync_response(self, params: Dict) -> AnthropicResponse:
        """同步请求处理"""
        response = self._client.chat.completions.create(**params)

        content_text = response.choices[0].message.content or ""

        return AnthropicResponse(
            id=f"msg_{int(time.time() * 1000)}",
            type="message",
            role="assistant",
            content=[ContentBlock(type="text", text=content_text)],
            model=response.model,
            stop_reason=response.choices[0].finish_reason,
            usage=Usage(
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0
            )
        )

    def _stream_response(self, params: Dict) -> Generator:
        """流式请求处理"""
        stream = self._client.chat.completions.create(
            **params,
            stream_options={"include_usage": True}
        )

        collected_text = ""
        input_tokens = 0
        output_tokens = 0

        for chunk in stream:
            # 收集内容
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                collected_text += content
                yield StreamEvent(
                    type="content_block_delta",
                    delta={"text": content},
                    index=0
                )

            # 收集 token 使用统计
            if hasattr(chunk, 'usage') and chunk.usage:
                input_tokens = chunk.usage.prompt_tokens
                output_tokens = chunk.usage.completion_tokens

        # 发送最终事件
        yield StreamEvent(
            type="message_stop",
            delta={},
            index=0,
            final_response=AnthropicResponse(
                id=f"msg_{int(time.time() * 1000)}",
                type="message",
                role="assistant",
                content=[ContentBlock(type="text", text=collected_text)],
                model=params["model"],
                stop_reason="end_turn",
                usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens)
            )
        )


@dataclass
class StreamEvent:
    """流式响应事件"""
    type: str
    delta: Dict
    index: int
    final_response: Optional[AnthropicResponse] = None


class StreamWrapper:
    """流式响应包装器，提供 Anthropic 风格的接口"""

    def __init__(self, generator: Generator, client: 'AnthropicAdapter'):
        self._generator = generator
        self._client = client
        self._text_stream = None
        self._final_response = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    @property
    def text_stream(self) -> Generator[str, None, None]:
        """文本流迭代器"""
        for event in self._generator:
            if event.type == "content_block_delta" and "text" in event.delta:
                yield event.delta["text"]
            elif event.type == "message_stop" and event.final_response:
                self._final_response = event.final_response

    def get_final_message(self) -> Optional[AnthropicResponse]:
        """获取最终消息"""
        return self._final_response


class Messages:
    """消息 API 端点"""

    def __init__(self, client: AnthropicAdapter):
        self._client = client

    def create(
        self,
        model: str,
        max_tokens: int,
        messages: List[Dict],
        stream: bool = False,
        **kwargs
    ) -> Union[AnthropicResponse, StreamWrapper]:
        """
        创建消息

        Args:
            model: 模型名称
            max_tokens: 最大输出 token 数
            messages: 消息列表
            stream: 是否使用流式输出
            **kwargs: 其他参数

        Returns:
            AnthropicResponse 或 StreamWrapper
        """
        if stream:
            generator = self._client._create_response(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                stream=True,
                **kwargs
            )
            return StreamWrapper(generator, self._client)
        else:
            return self._client._create_response(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                stream=False,
                **kwargs
            )

    def stream(
        self,
        model: str,
        max_tokens: int,
        messages: List[Dict],
        **kwargs
    ) -> StreamWrapper:
        """
        流式创建消息

        Args:
            model: 模型名称
            max_tokens: 最大输出 token 数
            messages: 消息列表
            **kwargs: 其他参数

        Returns:
            StreamWrapper
        """
        generator = self._client._create_response(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            stream=True,
            **kwargs
        )
        return StreamWrapper(generator, self._client)


# 便捷函数
def create_client(
    api_key: str,
    base_url: str = "http://aiapi.tcy365.net:82",
    default_model: str = "glm-5"
) -> AnthropicAdapter:
    """
    创建 Anthropic 适配器客户端

    Args:
        api_key: API 密钥
        base_url: 聚合平台基础 URL
        default_model: 默认使用的模型

    Returns:
        AnthropicAdapter 实例
    """
    return AnthropicAdapter(
        api_key=api_key,
        base_url=base_url,
        default_model=default_model
    )