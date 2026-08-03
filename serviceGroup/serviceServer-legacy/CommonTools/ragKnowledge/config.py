"""RAG 知识问答配置"""

import os
import json

# 基础路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(os.path.dirname(BASE_DIR))

# 知识库文档目录（保持在 src/knowledgeLib）
KNOWLEDGE_LIB_DIR = os.path.join(PROJECT_DIR, 'src', 'knowledgeLib')

# ChromaDB 持久化目录
CHROMA_DB_DIR = os.path.join(BASE_DIR, 'chroma_data')

# 索引状态文件
INDEX_STATUS_FILE = os.path.join(BASE_DIR, 'index_status.json')

# 模型配置文件
MODEL_CONFIG_FILE = os.path.join(BASE_DIR, 'model_config.json')

# 支持的文档格式
SUPPORTED_FORMATS = ['.md', '.txt', '.json']

# 文档分片配置
CHUNK_SIZE = 800       # 小分片大小
CHUNK_OVERLAY = 100    # 重叠字符数

# 父文档检索配置
PARENT_CHUNK_SIZE = 2000   # 父文档块大小（更大的上下文）
ENABLE_PARENT_RETRIEVAL = True  # 是否启用父文档检索

# 语义分片配置
ENABLE_SEMANTIC_CHUNKING = True  # 是否启用语义分片
SEMANTIC_THRESHOLD = 0.5    # 语义分割阈值（embedding 相似度低于此值时分割）
MIN_CHUNK_SIZE = 100        # 最小分片大小
MAX_CHUNK_SIZE = 1200       # 最大分片大小

# 元数据增强配置
ENABLE_METADATA_ENHANCEMENT = True  # 是否启用元数据增强（关键词/摘要提取）

# 召回配置
RETRIEVE_TOP_K = 10  # 召回 10 个片段（增加候选数量）
RERANK_TOP_K = 5     # 重排后保留 5 个

# 同义词映射（用于关键词扩展）
SYNONYM_MAP = {
    '充值': ['购买', '加', '添加', '充值', '买'],
    '购买': ['充值', '加', '添加', '买', '购买'],
    '加': ['充值', '购买', '添加', '增加'],
    '通宝': ['通宝'],
    "游戏货币":["通宝","银子","积分","金币","金豆","钻石"],
    '测试': ['测试', '测试环境', 'sandbox', '沙盒'],
    '测试环境': ['测试', '测试环境', 'sandbox', '沙盒',"125"],
    '模拟': ['模拟', '仿真', 'fake', 'mock'],
    "888":["外网测试","待发","发发发","外网测试环境","125之后"],
    "正式":["正式","正式环境","888之后"],
    "川麻":["xzmp","xzmk","四川麻将","血战麻将","红中麻将"],
    "斗地主":["zgda","zgde","zgdx","斗地主游戏","斗地主规则"],
    "渠道":["wxan","wxios","mergean","tcyan","tcyios","unknown"],
    "李真":["四川麻将开发","川麻","rag问答","Web 服务管理工具","serviceServer","川麻规则"],
    "事故":["线上事故","外网正式","事故报告"],
    "微信":["小游戏","小程序","公众后台","小程序助手","开发者工具"]
}

# 查询重写提示词
QUERY_REWRITE_PROMPT = """你是一个查询优化专家。请将用户的模糊查询改写为更标准、更精确的表述，以便在知识库中检索。"

用户原始查询：{query}

改写要求：
1. 保留用户的核心意图
2. 使用知识库中可能出现的标准术语
3. 去掉无关的修饰词，突出关键概念
4. 如果查询涉及"测试环境"，保留这个关键信息
5. 输出简洁的改写结果，不要解释

请直接输出改写后的查询（一句话）："""

# Embedding 模型列表
EMBEDDING_MODELS = {
    'text2vec-base-chinese': {
        'name': 'shibing624/text2vec-base-chinese',
        'display': 'Text2Vec 中文',
        'dimension': 768,
        'language': '中文优先',
        'description': '中文专用模型，效果稳定'
    },
    'all-MiniLM-L6-v2': {
        'name': 'sentence-transformers/all-MiniLM-L6-v2',
        'display': 'MiniLM 英文',
        'dimension': 384,
        'language': '英文优先',
        'description': '轻量快速，适合英文'
    },
    'bge-m3': {
        'name': 'BAAI/bge-m3',
        'display': 'BGE-M3 多语言',
        'dimension': 1024,
        'language': '多语言',
        'description': 'BAAI开源，中文效果最佳'
    }
}

# 默认模型
DEFAULT_EMBEDDING_MODEL = 'text2vec-base-chinese'

def get_current_embedding_model():
    """获取当前选中的嵌入模型"""
    if os.path.exists(MODEL_CONFIG_FILE):
        try:
            with open(MODEL_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                model_key = config.get('current_model', DEFAULT_EMBEDDING_MODEL)
                if model_key in EMBEDDING_MODELS:
                    return model_key
        except:
            pass
    return DEFAULT_EMBEDDING_MODEL

def set_current_embedding_model(model_key):
    """设置当前嵌入模型"""
    if model_key not in EMBEDDING_MODELS:
        return False

    config = {'current_model': model_key}
    with open(MODEL_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False)
    return True

def get_embedding_model_info():
    """获取所有模型信息"""
    current = get_current_embedding_model()
    models = []
    for key, info in EMBEDDING_MODELS.items():
        models.append({
            'key': key,
            'display': info['display'],
            'dimension': info['dimension'],
            'language': info['language'],
            'description': info['description'],
            'is_current': key == current
        })
    return {
        'current': current,
        'current_info': EMBEDDING_MODELS[current],
        'models': models
    }

# LLM API 配置（参考 speedTest.py）
LLM_BASE_URL = "http://aiapi.tcy365.net:82/v1"
LLM_API_KEY = "sk-dO3EZ0tc0PeU92wRhkPUp60sukthYvaaN1BJ1DeKJNlAl9c3"

# 默认生成模型
DEFAULT_MODEL = "doubao-seed-2.0-pro"

# 定时索引时间（每天凌晨 3:00）
SCHEDULE_HOUR = 3
SCHEDULE_MINUTE = 0

# 飞书文档导出配置
# 如果 feishu-doc-export.exe 在系统 PATH 中，可以只写文件名
# 否则需要填写完整路径，例如: "D:/tools/feishu-doc-export.exe"
FEISHU_EXPORT_PATH = "feishu-doc-export.exe"
FEISHU_APP_ID = "***REMOVED_FEISHU_APP_ID***"
FEISHU_APP_SECRET = "***REMOVED_FEISHU_APP_SECRET***"
FEISHU_SPACE_ID = "7504186247792099332"
FEISHU_EXPORT_TYPE = "md"  # 导出格式：md 或 json

# 重排提示词
RERANK_PROMPT = """你是一个文档相关性评估专家。请仔细评估以下每个文档片段与用户问题的相关性。

用户问题：{query}

请为每个片段评分（0-100分），评分标准：
- 90-100分：片段直接回答了问题，包含关键信息
- 70-89分：片段与问题高度相关，提供重要背景信息
- 50-69分：片段与问题部分相关，可能提供一些线索
- 30-49分：片段与问题有弱关联
- 0-29分：片段与问题无关或关联极弱

文档片段：
{chunks}

请严格按照以下格式输出评分（只输出评分，不要解释）：
片段1:分数
片段2:分数
片段3:分数
片段4:分数
片段5:分数"""

# 生成提示词模板
GENERATE_PROMPT = """基于以下知识库内容回答用户问题。如果知识库中没有相关信息，请诚实说明。

知识库内容：
{context}

用户问题：{query}

请用中文回答，回答要准确、简洁。"""