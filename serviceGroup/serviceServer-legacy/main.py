import os
# 兼容旧版 protobuf 生成的代码
os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = 'python'

import JsonConfigParser
import CustomRoute

if __name__ == '__main__':
    JsonConfigParser.create_defaultConfig()

    # 初始化 RAG 知识问答模块
    try:
        pass
        # from CommonTools.ragKnowledge import init_rag
        # init_rag()
    except ImportError as e:
        print(f"[Warning] RAG 模块初始化失败，请确保已安装依赖: {e}")
    except Exception as e:
        print(f"[Warning] RAG 模块初始化异常: {e}")

    # 标准 Flask 启动（不需要 WebSocket）
    # strangler: port 走 env (旧 Flask 移 :5099, Rust 占 :5000 反代)
    port = int(os.environ.get('SERVICESVR_PORT', '5000'))
    CustomRoute.app.run(host='0.0.0.0', port=port, debug=False)