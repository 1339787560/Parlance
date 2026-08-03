"""
Anthropic 适配器测试脚本

用于测试 anthropic_adapter.py 是否正常工作。
支持交互式聊天和流式输出测试。
"""

import os
import sys
import io

# 设置标准输出编码为 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from anthropic_adapter import AnthropicAdapter, create_client

# ================= 配置区域 =================
API_KEY = "sk-dO3EZ0tc0PeU92wRhkPUp60sukthYvaaN1BJ1DeKJNlAl9c3"
BASE_URL = "http://aiapi.tcy365.net:82"
DEFAULT_MODEL = "glm-5"

# 可用模型列表
AVAILABLE_MODELS = [
    "deepseek-v3.2",
    "deepseek-v3.2-thinking",
    "glm-4.7",
    "glm-5",
    "glm-5.1",
    "kimi-k2.6",
    "MiniMax-M2.1",
    "MiniMax-M2.5",
    "MiniMax-M2.7",
    "doubao-seed-2.0-code",
    "doubao-seed-2.0-pro",
    "step3.5-flash-fp8",
    "gpt-5.5",
    "claude-opus-4-7",
    "deepseek-v4-flash",
    "deepseek-v4-pro"
]
# ============================================


def test_basic_call(client: AnthropicAdapter):
    """测试基本调用"""
    print("\n" + "=" * 50)
    print("测试 1: 基本调用 (非流式)")
    print("=" * 50)

    try:
        response = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=100,
            messages=[
                {"role": "user", "content": "你好，请用一句话介绍你自己。"}
            ]
        )

        print(f"模型: {response.model}")
        print(f"回复: {response.content[0].text}")
        print(f"Token 使用: 输入={response.usage.input_tokens}, 输出={response.usage.output_tokens}")
        print("✓ 基本调用测试通过")
        return True

    except Exception as e:
        print(f"✗ 基本调用测试失败: {e}")
        return False


def test_stream_call(client: AnthropicAdapter):
    """测试流式调用"""
    print("\n" + "=" * 50)
    print("测试 2: 流式调用")
    print("=" * 50)

    try:
        with client.messages.stream(
            model=DEFAULT_MODEL,
            max_tokens=100,
            messages=[
                {"role": "user", "content": "请数从 1 到 5，每个数字一行。"}
            ]
        ) as stream:
            print("流式输出: ", end="", flush=True)
            for text in stream.text_stream:
                print(text, end="", flush=True)
            print()

        final = stream.get_final_message()
        if final:
            print(f"Token 使用: 输入={final.usage.input_tokens}, 输出={final.usage.output_tokens}")
        print("✓ 流式调用测试通过")
        return True

    except Exception as e:
        print(f"✗ 流式调用测试失败: {e}")
        return False


def test_system_message(client: AnthropicAdapter):
    """测试系统消息"""
    print("\n" + "=" * 50)
    print("测试 3: 系统消息")
    print("=" * 50)

    try:
        response = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=100,
            messages=[
                {"role": "system", "content": "你是一个只会说'喵'的猫。"},
                {"role": "user", "content": "你好，请介绍一下你自己。"}
            ]
        )

        print(f"回复: {response.content[0].text}")
        print("✓ 系统消息测试通过")
        return True

    except Exception as e:
        print(f"✗ 系统消息测试失败: {e}")
        return False


def test_multi_turn(client: AnthropicAdapter):
    """测试多轮对话"""
    print("\n" + "=" * 50)
    print("测试 4: 多轮对话")
    print("=" * 50)

    try:
        messages = [
            {"role": "user", "content": "我叫小明。"}
        ]

        response1 = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=100,
            messages=messages
        )
        print(f"第一轮回复: {response1.content[0].text}")

        messages.append({"role": "assistant", "content": response1.content[0].text})
        messages.append({"role": "user", "content": "我叫什么名字？"})

        response2 = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=100,
            messages=messages
        )
        print(f"第二轮回复: {response2.content[0].text}")
        print("✓ 多轮对话测试通过")
        return True

    except Exception as e:
        print(f"✗ 多轮对话测试失败: {e}")
        return False


def interactive_chat(client: AnthropicAdapter):
    """交互式聊天模式"""
    print("\n" + "=" * 50)
    print("交互式聊天模式")
    print("=" * 50)
    print(f"当前模型: {DEFAULT_MODEL}")
    print("输入 'quit' 退出, 'stream' 切换流式模式, 'model <name>' 切换模型")
    print(f"可用模型: {', '.join(AVAILABLE_MODELS)}")
    print("=" * 50 + "\n")

    use_stream = True
    current_model = DEFAULT_MODEL
    messages = []

    while True:
        try:
            user_input = input("你: ").strip()

            if not user_input:
                continue

            if user_input.lower() == 'quit':
                print("再见!")
                break

            if user_input.lower() == 'stream':
                use_stream = not use_stream
                print(f"流式模式: {'开启' if use_stream else '关闭'}")
                continue

            if user_input.lower().startswith('model '):
                new_model = user_input[6:].strip()
                if new_model in AVAILABLE_MODELS:
                    current_model = new_model
                    print(f"已切换到模型: {current_model}")
                else:
                    print(f"未知模型: {new_model}")
                continue

            messages.append({"role": "user", "content": user_input})

            if use_stream:
                print("助手: ", end="", flush=True)
                full_response = ""
                with client.messages.stream(
                    model=current_model,
                    max_tokens=1024,
                    messages=messages
                ) as stream:
                    for text in stream.text_stream:
                        print(text, end="", flush=True)
                        full_response += text
                print()
                messages.append({"role": "assistant", "content": full_response})
            else:
                response = client.messages.create(
                    model=current_model,
                    max_tokens=1024,
                    messages=messages
                )
                print(f"助手: {response.content[0].text}")
                messages.append({"role": "assistant", "content": response.content[0].text})

        except KeyboardInterrupt:
            print("\n再见!")
            break
        except Exception as e:
            print(f"错误: {e}")


def main():
    """主函数"""
    print("=" * 50)
    print("Anthropic 适配器测试")
    print("=" * 50)
    print(f"API 地址: {BASE_URL}")
    print(f"默认模型: {DEFAULT_MODEL}")
    print()

    # 创建客户端
    client = create_client(
        api_key=API_KEY,
        base_url=BASE_URL,
        default_model=DEFAULT_MODEL
    )

    # 运行基本测试
    tests = [
        ("基本调用", lambda: test_basic_call(client)),
        ("流式调用", lambda: test_stream_call(client)),
        ("系统消息", lambda: test_system_message(client)),
        ("多轮对话", lambda: test_multi_turn(client)),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"✗ {name} 测试异常: {e}")
            failed += 1

    # 打印测试结果
    print("\n" + "=" * 50)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 50)

    # 进入交互式聊天
    if passed > 0:
        print("\n所有基本测试完成，进入交互式聊天模式...\n")
        interactive_chat(client)
    else:
        print("\n所有测试失败，请检查配置和网络连接。")


if __name__ == "__main__":
    main()