"""RAG 核心引擎：索引、召回、重排、生成"""

import os
import json
import time
import re
import jieba
from typing import List, Dict, Generator, Optional
from openai import OpenAI

# 设置 HuggingFace 镜像（国内网络）
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings

# BM25 混合检索
try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except ImportError:
    BM25_AVAILABLE = False
    print("[RAG] rank_bm25 未安装，将只使用向量检索")

from .config import (
    CHROMA_DB_DIR,
    INDEX_STATUS_FILE,
    EMBEDDING_MODELS,
    get_current_embedding_model,
    set_current_embedding_model,
    get_embedding_model_info,
    RETRIEVE_TOP_K,
    RERANK_TOP_K,
    LLM_BASE_URL,
    LLM_API_KEY,
    DEFAULT_MODEL,
    RERANK_PROMPT,
    GENERATE_PROMPT,
    KNOWLEDGE_LIB_DIR,
    SYNONYM_MAP,
    QUERY_REWRITE_PROMPT,
    ENABLE_PARENT_RETRIEVAL,
)
from .document_processor import (
    process_all_documents,
    get_library_mtime,
    get_document_list,
    get_parent_chunk,
)
from .evaluation import RAGEvaluator


class RAGEngine:
    """RAG 知识问答引擎（向量 + BM25 混合检索，支持模型切换）"""

    def __init__(self):
        self.embedding_model = None
        self.current_model_key = None
        self.chroma_client = None
        self.collection = None
        self.llm_client = None
        self.index_status = {}

        # BM25 索引
        self.bm25_index = None
        self.bm25_documents = []  # 存储文档内容用于 BM25

        # 评估器
        self.evaluator = RAGEvaluator()

        self._init_embedding_model()
        self._init_chroma()
        self._init_llm_client()
        self._load_index_status()

    def _init_embedding_model(self):
        """初始化 embedding 模型（使用动态配置）"""
        self.current_model_key = get_current_embedding_model()
        model_info = EMBEDDING_MODELS[self.current_model_key]
        model_name = model_info['name']

        try:
            self.embedding_model = SentenceTransformer(
                model_name,
                trust_remote_code=True
            )
            print(f"[RAG] Embedding 模型加载成功: {model_info['display']} ({model_name})")
        except Exception as e:
            print(f"[RAG] Embedding 模型加载失败: {str(e)}")
            # 尝试备用模型
            try:
                fallback_model = 'shibing624/text2vec-base-chinese'
                print(f"[RAG] 尝试备用模型: {fallback_model}")
                self.embedding_model = SentenceTransformer(fallback_model)
                self.current_model_key = 'text2vec-base-chinese'
                print(f"[RAG] 备用模型加载成功")
            except Exception as e2:
                print(f"[RAG] 备用模型也失败: {str(e2)}")
                self.embedding_model = None

    def switch_embedding_model(self, model_key: str) -> Dict:
        """切换嵌入模型"""
        if model_key not in EMBEDDING_MODELS:
            return {'success': False, 'message': f'模型 {model_key} 不存在'}

        if model_key == self.current_model_key:
            return {'success': True, 'message': '模型已切换（无需重建索引）', 'need_reindex': False}

        model_info = EMBEDDING_MODELS[model_key]
        model_name = model_info['name']

        try:
            # 加载新模型
            new_model = SentenceTransformer(model_name, trust_remote_code=True)

            # 更新实例
            self.embedding_model = new_model
            self.current_model_key = model_key

            # 保存配置
            set_current_embedding_model(model_key)

            # 检查维度是否变化
            old_dim = self.index_status.get('embedding_dimension', 0)
            new_dim = model_info['dimension']
            need_reindex = old_dim != new_dim or self.collection.count() > 0

            return {
                'success': True,
                'message': f'模型已切换为 {model_info["display"]}',
                'model': model_info['display'],
                'dimension': new_dim,
                'need_reindex': need_reindex,
                'warning': '切换模型后需要重建向量索引！' if need_reindex else None
            }

        except Exception as e:
            return {'success': False, 'message': f'模型加载失败: {str(e)}'}

    def _init_chroma(self):
        """初始化 ChromaDB"""
        try:
            # 确保目录存在
            os.makedirs(CHROMA_DB_DIR, exist_ok=True)

            self.chroma_client = chromadb.PersistentClient(
                path=CHROMA_DB_DIR,
                settings=Settings(anonymized_telemetry=False)
            )

            # 获取或创建集合
            self.collection = self.chroma_client.get_or_create_collection(
                name="knowledge_lib",
                metadata={"hnsw:space": "cosine"}
            )
            print(f"[RAG] ChromaDB 初始化成功，当前文档数: {self.collection.count()}")

            # 加载 BM25 缓存
            self._load_bm25_cache()

        except Exception as e:
            print(f"[RAG] ChromaDB 初始化失败: {str(e)}")
            self.chroma_client = None
            self.collection = None

    def _load_bm25_cache(self):
        """加载 BM25 缓存"""
        if not BM25_AVAILABLE:
            return

        bm25_cache_file = os.path.join(CHROMA_DB_DIR, 'bm25_cache.json')
        if os.path.exists(bm25_cache_file):
            try:
                with open(bm25_cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                self.bm25_documents = cache_data.get('documents', [])
                if self.bm25_documents:
                    tokenized_docs = [jieba.lcut(doc) for doc in self.bm25_documents]
                    self.bm25_index = BM25Okapi(tokenized_docs)
                    print(f"[RAG] BM25 缓存加载成功，文档数: {len(self.bm25_documents)}")
            except Exception as e:
                print(f"[RAG] BM25 缓存加载失败: {str(e)}")

    def _init_llm_client(self):
        """初始化 LLM 客户端"""
        try:
            self.llm_client = OpenAI(
                api_key=LLM_API_KEY,
                base_url=LLM_BASE_URL
            )
            print(f"[RAG] LLM 客户端初始化成功")
        except Exception as e:
            print(f"[RAG] LLM 客户端初始化失败: {str(e)}")
            self.llm_client = None

    def _load_index_status(self):
        """加载索引状态"""
        if os.path.exists(INDEX_STATUS_FILE):
            try:
                with open(INDEX_STATUS_FILE, 'r', encoding='utf-8') as f:
                    self.index_status = json.load(f)
            except Exception as e:
                print(f"[RAG] 加载索引状态失败: {str(e)}")
                self.index_status = {}

    def _save_index_status(self):
        """保存索引状态"""
        try:
            with open(INDEX_STATUS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.index_status, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[RAG] 保存索引状态失败: {str(e)}")

    def build_index(self) -> Dict:
        """构建索引（向量 + BM25，支持语义分片和父文档检索）"""
        if not self.embedding_model or not self.collection:
            return {'success': False, 'message': 'RAG 引擎未初始化'}

        try:
            start_time = time.time()

            # 处理所有文档（传入 embedding 模型和 LLM 客户端）
            from .config import ENABLE_SEMANTIC_CHUNKING, ENABLE_PARENT_RETRIEVAL
            print(f"[RAG] 分片策略: 语义分片={ENABLE_SEMANTIC_CHUNKING}, 父文档检索={ENABLE_PARENT_RETRIEVAL}")

            chunks, doc_stats = process_all_documents(
                embedding_model=self.embedding_model if ENABLE_SEMANTIC_CHUNKING else None,
                llm_client=self.llm_client
            )

            if not chunks:
                return {
                    'success': False,
                    'message': f'知识库中没有有效文档。扫描: {doc_stats["scanned"]}, 空内容: {doc_stats["empty_content"]}, 无分片: {doc_stats["no_chunks"]}',
                    'doc_stats': doc_stats
                }

            # 清空现有索引
            if self.collection.count() > 0:
                existing_ids = self.collection.get()['ids']
                if existing_ids:
                    self.collection.delete(ids=existing_ids)

            # 生成 embeddings
            contents = [chunk['content'] for chunk in chunks]
            embeddings = self.embedding_model.encode(contents, show_progress_bar=True)

            # 构建 BM25 索引（使用 jieba 分词 + 关键词增强）
            if BM25_AVAILABLE:
                tokenized_docs = []
                for i, doc in enumerate(contents):
                    tokens = jieba.lcut(doc)
                    # 添加元数据中的关键词
                    if chunks[i].get('keywords'):
                        tokens.extend(chunks[i]['keywords'])
                    tokenized_docs.append(tokens)

                self.bm25_index = BM25Okapi(tokenized_docs)
                self.bm25_documents = contents
                print(f"[RAG] BM25 索引构建完成，文档数: {len(contents)}")

            # 构建元数据（包含增强信息）
            ids = [f"chunk_{i}" for i in range(len(chunks))]
            metadatas = []
            for i, chunk in enumerate(chunks):
                meta = {
                    'source': chunk['source'],
                    'section': chunk.get('section', ''),
                    'doc_title': chunk.get('doc_title', ''),
                    'index': chunk.get('index', i),
                    'doc_mtime': chunk.get('doc_mtime', 0),
                    'semantic_split': chunk.get('semantic_split', False),
                }
                # 添加关键词（用于检索增强）
                if chunk.get('keywords'):
                    meta['keywords'] = ','.join(chunk['keywords'][:5])
                metadatas.append(meta)

            # 存入 ChromaDB
            self.collection.add(
                ids=ids,
                embeddings=embeddings.tolist(),
                documents=contents,
                metadatas=metadatas
            )

            # 保存 BM25 索引和元数据到文件
            if BM25_AVAILABLE:
                bm25_cache_file = os.path.join(CHROMA_DB_DIR, 'bm25_cache.json')
                cache_data = {
                    'documents': contents,
                    'metadatas': metadatas
                }
                with open(bm25_cache_file, 'w', encoding='utf-8') as f:
                    json.dump(cache_data, f, ensure_ascii=False)

            # 更新状态
            elapsed = time.time() - start_time
            doc_count = len(set(c['source'] for c in chunks))
            self.index_status = {
                'chunk_count': len(chunks),
                'doc_count': doc_count,
                'scanned_count': doc_stats['scanned'],
                'last_index_time': time.time(),
                'elapsed_seconds': elapsed,
                'library_mtime': get_library_mtime(),
                'embedding_model': self.current_model_key,
                'embedding_dimension': EMBEDDING_MODELS[self.current_model_key]['dimension'],
                'semantic_chunking': ENABLE_SEMANTIC_CHUNKING,
                'parent_retrieval': ENABLE_PARENT_RETRIEVAL,
                'doc_stats': doc_stats
            }
            self._save_index_status()

            return {
                'success': True,
                'message': f'索引构建成功，共 {len(chunks)} 个分片',
                'chunk_count': len(chunks),
                'doc_count': doc_count,
                'scanned_count': doc_stats['scanned'],
                'elapsed': elapsed,
                'semantic_chunking': ENABLE_SEMANTIC_CHUNKING,
                'doc_stats': doc_stats
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'success': False, 'message': f'索引构建失败: {str(e)}'}

    def retrieve(self, query: str) -> List[Dict]:
        """混合召回：向量检索 + BM25 关键词检索（含查询优化）"""
        if not self.embedding_model or not self.collection:
            return []

        if self.collection.count() == 0:
            return []

        try:
            # 0. 查询重写（用 LLM 将模糊查询改写为标准表述）
            rewritten_query = self._rewrite_query(query)
            original_query = query

            # 使用改写后的查询进行检索，但保留原始查询用于向量检索
            search_query = rewritten_query if rewritten_query else query
            print(f"[RAG] 原始查询: {original_query}")
            if rewritten_query:
                print(f"[RAG] 改写查询: {rewritten_query}")

            # 1. 向量检索（使用原始查询和改写查询的组合）
            # 对原始查询和改写查询都进行向量检索，合并结果
            all_vector_chunks = {}

            # 原始查询向量检索
            query_embedding = self.embedding_model.encode([original_query])[0]
            vector_results = self.collection.query(
                query_embeddings=[query_embedding.tolist()],
                n_results=RETRIEVE_TOP_K,
                include=['documents', 'metadatas', 'distances']
            )

            for i in range(len(vector_results['ids'][0])):
                chunk_id = vector_results['ids'][0][i]
                all_vector_chunks[chunk_id] = {
                    'id': chunk_id,
                    'content': vector_results['documents'][0][i],
                    'source': vector_results['metadatas'][0][i]['source'],
                    'distance': vector_results['distances'][0][i],
                    'score': 1 - vector_results['distances'][0][i],
                    'retrieval_type': 'vector'
                }

            # 如果有改写查询，也进行向量检索（权重较低）
            if rewritten_query and rewritten_query != original_query:
                rewritten_embedding = self.embedding_model.encode([rewritten_query])[0]
                rewritten_results = self.collection.query(
                    query_embeddings=[rewritten_embedding.tolist()],
                    n_results=RETRIEVE_TOP_K // 2,
                    include=['documents', 'metadatas', 'distances']
                )

                for i in range(len(rewritten_results['ids'][0])):
                    chunk_id = rewritten_results['ids'][0][i]
                    rewritten_score = 1 - rewritten_results['distances'][0][i]
                    if chunk_id in all_vector_chunks:
                        # 合并分数：原始查询权重 0.7，改写查询权重 0.3
                        all_vector_chunks[chunk_id]['score'] = (
                            all_vector_chunks[chunk_id]['score'] * 0.7 + rewritten_score * 0.3
                        )
                    else:
                        all_vector_chunks[chunk_id] = {
                            'id': chunk_id,
                            'content': rewritten_results['documents'][0][i],
                            'source': rewritten_results['metadatas'][0][i]['source'],
                            'distance': rewritten_results['distances'][0][i],
                            'score': rewritten_score * 0.3,
                            'retrieval_type': 'vector_rewritten'
                        }

            vector_chunks = list(all_vector_chunks.values())

            # 2. BM25 关键词检索（含同义词扩展）
            bm25_chunks = []
            if BM25_AVAILABLE and self.bm25_index:
                # 同义词扩展
                expanded_tokens = self._expand_query_tokens(search_query)
                print(f"[RAG] BM25 扩展词: {expanded_tokens}")

                bm25_scores = self.bm25_index.get_scores(expanded_tokens)
                top_indices = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:RETRIEVE_TOP_K]

                for idx in top_indices:
                    if bm25_scores[idx] > 0:
                        try:
                            doc_data = self.collection.get(ids=[f"chunk_{idx}"])
                            if doc_data['ids']:
                                bm25_chunks.append({
                                    'id': doc_data['ids'][0],
                                    'content': doc_data['documents'][0],
                                    'source': doc_data['metadatas'][0]['source'],
                                    'bm25_score': bm25_scores[idx],
                                    'score': bm25_scores[idx] / 10,
                                    'retrieval_type': 'bm25'
                                })
                        except:
                            bm25_chunks.append({
                                'id': f"chunk_{idx}",
                                'content': self.bm25_documents[idx],
                                'source': 'unknown',
                                'bm25_score': bm25_scores[idx],
                                'score': bm25_scores[idx] / 10,
                                'retrieval_type': 'bm25'
                            })

            # 3. 合并结果（去重 + 加权融合）
            all_chunks = {}

            for chunk in vector_chunks:
                key = chunk['id']
                all_chunks[key] = chunk
                all_chunks[key]['final_score'] = chunk['score'] * 0.6

            for chunk in bm25_chunks:
                key = chunk['id']
                if key in all_chunks:
                    all_chunks[key]['final_score'] = all_chunks[key]['score'] * 0.6 + chunk['score'] * 0.4
                    all_chunks[key]['bm25_score'] = chunk['bm25_score']
                    all_chunks[key]['retrieval_type'] = 'hybrid'
                else:
                    all_chunks[key] = chunk
                    all_chunks[key]['final_score'] = chunk['score'] * 0.4

            # 按最终分数排序
            sorted_chunks = sorted(all_chunks.values(), key=lambda c: c['final_score'], reverse=True)

            # 返回前 RETRIEVE_TOP_K 个
            final_chunks = sorted_chunks[:RETRIEVE_TOP_K]
            for i, chunk in enumerate(final_chunks):
                chunk['index'] = i + 1

            # 父文档检索：扩展上下文
            if ENABLE_PARENT_RETRIEVAL:
                final_chunks = self._expand_with_parent_context(final_chunks)

            return final_chunks

        except Exception as e:
            print(f"[RAG] 召回失败: {str(e)}")
            return []

    def _rewrite_query(self, query: str) -> Optional[str]:
        """使用 LLM 重写查询，使其更易于检索"""
        if not self.llm_client:
            return None

        try:
            prompt = QUERY_REWRITE_PROMPT.format(query=query)
            response = self.llm_client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.3  # 低温度，更稳定的输出
            )
            rewritten = response.choices[0].message.content.strip()
            # 去掉可能的前缀说明
            if ':' in rewritten:
                rewritten = rewritten.split(':')[-1].strip()
            return rewritten if rewritten and len(rewritten) < 100 else None
        except Exception as e:
            print(f"[RAG] 查询重写失败: {str(e)}")
            return None

    def _expand_query_tokens(self, query: str) -> List[str]:
        """扩展查询词，添加同义词"""
        tokens = jieba.lcut(query)
        expanded = list(tokens)

        for token in tokens:
            if token in SYNONYM_MAP:
                synonyms = SYNONYM_MAP[token]
                for syn in synonyms:
                    if syn not in expanded:
                        expanded.append(syn)

        return expanded

    def _expand_with_parent_context(self, chunks: List[Dict]) -> List[Dict]:
        """用父文档扩展上下文（父文档检索）"""
        if not ENABLE_PARENT_RETRIEVAL:
            return chunks

        expanded_chunks = []
        for chunk in chunks:
            # 尝试获取父文档块
            parent = get_parent_chunk(chunk)

            if parent:
                # 创建扩展后的块，包含更大的上下文
                expanded_chunk = chunk.copy()
                expanded_chunk['parent_content'] = parent.get('content', '')
                expanded_chunk['has_parent_context'] = True

                # 如果父文档内容比子块大很多，使用父文档作为上下文
                if len(parent.get('content', '')) > len(chunk.get('content', '')) * 1.5:
                    expanded_chunk['context_content'] = parent['content']
                else:
                    expanded_chunk['context_content'] = chunk['content']

                expanded_chunks.append(expanded_chunk)
            else:
                chunk['has_parent_context'] = False
                chunk['context_content'] = chunk['content']
                expanded_chunks.append(chunk)

        return expanded_chunks

    def rerank(self, query: str, chunks: List[Dict]) -> List[Dict]:
        """使用 LLM 重排"""
        if not self.llm_client or not chunks:
            return chunks[:RERANK_TOP_K]

        try:
            # 构建重排提示（重新编号片段）
            chunk_text = "\n\n".join([
                f"片段{i+1}（来源: {chunk['source']}）:\n{chunk['content'][:500]}..."  # 截断避免太长
                for i, chunk in enumerate(chunks)
            ])

            prompt = RERANK_PROMPT.format(query=query, chunks=chunk_text)

            # 调用 LLM
            response = self.llm_client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200
            )

            scores_text = response.choices[0].message.content.strip()

            # 解析评分（匹配 "片段X:分数" 格式）
            scores = {}
            for line in scores_text.split('\n'):
                line = line.strip()
                # 匹配 "片段1:80" 或 "片段1: 80" 格式
                match = re.search(r'片段(\d+)\s*[:：]\s*(\d+)', line)
                if match:
                    idx = int(match.group(1))
                    score = int(match.group(2))
                    scores[idx] = score

            # 按评分排序（idx 是 1-based，映射到 chunks 列表）
            if scores and len(scores) >= 3:
                # 创建 (chunk, score) 对并排序
                scored_chunks = []
                for i, chunk in enumerate(chunks):
                    score = scores.get(i + 1, 0)  # i+1 因为片段编号从 1 开始
                    chunk['rerank_score'] = score
                    scored_chunks.append(chunk)

                sorted_chunks = sorted(scored_chunks, key=lambda c: c['rerank_score'], reverse=True)
                return sorted_chunks[:RERANK_TOP_K]

            # 如果解析失败，返回前 3 个
            return chunks[:RERANK_TOP_K]

        except Exception as e:
            print(f"[RAG] 重排失败: {str(e)}")
            return chunks[:RERANK_TOP_K]

    def generate_stream(self, query: str, chunks: List[Dict]) -> Generator[str, None, None]:
        """流式生成答案"""
        if not self.llm_client:
            yield "LLM 服务未初始化"
            return

        if not chunks:
            yield "知识库中没有找到相关信息。"
            return

        # 构建上下文
        context = "\n\n".join([
            f"【{chunk['source']}】\n{chunk['content']}"
            for chunk in chunks
        ])

        prompt = GENERATE_PROMPT.format(context=context, query=query)

        try:
            stream = self.llm_client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                max_tokens=1024
            )

            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            yield f"\n[生成失败: {str(e)}]"

    def query(self, question: str) -> Dict:
        """完整问答流程（返回结果用于前端展示）"""
        # 1. 召回
        retrieved_chunks = self.retrieve(question)

        if not retrieved_chunks:
            return {
                'success': False,
                'message': '知识库中没有找到相关信息',
                'retrieved': [],
                'reranked': [],
                'answer': ''
            }

        # 2. 重排
        reranked_chunks = self.rerank(question, retrieved_chunks)

        # 3. 生成
        answer_parts = []
        for part in self.generate_stream(question, reranked_chunks):
            answer_parts.append(part)
        answer = ''.join(answer_parts)

        return {
            'success': True,
            'retrieved': retrieved_chunks,
            'reranked': reranked_chunks,
            'answer': answer
        }

    def query_stream(self, question: str) -> Generator[Dict, None, None]:
        """流式问答（逐步返回结果，包含评估数据）"""
        # 1. 先返回召回结果
        retrieved_chunks = self.retrieve(question)

        # 评估召回效果
        retrieval_eval = self.evaluator.evaluate_retrieval(retrieved_chunks)

        yield {'type': 'retrieved', 'data': retrieved_chunks}
        yield {'type': 'retrieval_eval', 'data': retrieval_eval}

        if not retrieved_chunks:
            yield {'type': 'answer', 'data': '知识库中没有找到相关信息。'}
            yield {'type': 'eval_summary', 'data': self.evaluator.full_evaluation(retrieved_chunks, [], '')}
            return

        # 2. 重排
        reranked_chunks = self.rerank(question, retrieved_chunks)

        # 评估重排效果
        rerank_eval = self.evaluator.evaluate_rerank(retrieved_chunks, reranked_chunks)

        yield {'type': 'reranked', 'data': reranked_chunks}
        yield {'type': 'rerank_eval', 'data': rerank_eval}

        # 3. 流式生成答案
        answer_buffer = ""
        for part in self.generate_stream(question, reranked_chunks):
            answer_buffer += part
            yield {'type': 'answer_chunk', 'data': part}

        yield {'type': 'answer_done', 'data': answer_buffer}

        # 4. 返回完整评估报告
        full_eval = self.evaluator.full_evaluation(retrieved_chunks, reranked_chunks, answer_buffer)
        yield {'type': 'eval_summary', 'data': full_eval}

    def get_status(self) -> Dict:
        """获取引擎状态"""
        return {
            'initialized': self.embedding_model is not None and self.collection is not None,
            'chunk_count': self.index_status.get('chunk_count', 0),
            'doc_count': self.index_status.get('doc_count', 0),
            'scanned_count': self.index_status.get('scanned_count', self.index_status.get('doc_count', 0)),
            'last_index_time': self.index_status.get('last_index_time', 0),
            'library_mtime': self.index_status.get('library_mtime', 0),
            'current_library_mtime': get_library_mtime(),
            'needs_reindex': self._needs_reindex(),
            'current_model': self.current_model_key,
            'indexed_model': self.index_status.get('embedding_model', 'unknown'),
            'model_dimension': EMBEDDING_MODELS.get(self.current_model_key, {}).get('dimension', 0),
            'indexed_dimension': self.index_status.get('embedding_dimension', 0),
            'dimension_mismatch': self._check_dimension_mismatch(),
            'doc_stats': self.index_status.get('doc_stats', {})
        }

    def _check_dimension_mismatch(self) -> bool:
        """检查模型维度是否与索引匹配"""
        indexed_dim = self.index_status.get('embedding_dimension', 0)
        current_dim = EMBEDDING_MODELS.get(self.current_model_key, {}).get('dimension', 0)
        indexed_model = self.index_status.get('embedding_model', '')

        # 如果没有索引，不报 mismatch
        if indexed_dim == 0:
            return False

        # 模型或维度不同则 mismatch
        return indexed_model != self.current_model_key or indexed_dim != current_dim

    def _needs_reindex(self) -> bool:
        """检查是否需要重建索引"""
        if not self.index_status.get('last_index_time'):
            return True

        current_mtime = get_library_mtime()
        indexed_mtime = self.index_status.get('library_mtime', 0)

        return current_mtime > indexed_mtime

    def get_documents(self) -> List[Dict]:
        """获取知识库文档列表"""
        return get_document_list()


# 全局引擎实例
_engine: Optional[RAGEngine] = None


def get_engine() -> RAGEngine:
    """获取全局引擎实例"""
    global _engine
    if _engine is None:
        _engine = RAGEngine()
    return _engine


def init_engine() -> Dict:
    """初始化引擎（启动时调用，不自动重建索引）"""
    engine = get_engine()
    status = engine.get_status()

    # 不在启动时自动重建索引，仅提示状态
    if status['needs_reindex']:
        print("[RAG] 知识库有更新，需要重建索引（可通过前端手动触发或凌晨3点定时触发）")

    return engine.get_status()