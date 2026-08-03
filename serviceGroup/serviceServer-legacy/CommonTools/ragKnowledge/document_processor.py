"""文档处理器：扫描、分片知识库文档（支持语义分片、父文档检索）"""

import os
import json
import re
from typing import List, Dict, Optional, Tuple

from .config import (
    KNOWLEDGE_LIB_DIR,
    SUPPORTED_FORMATS,
    CHUNK_SIZE,
    CHUNK_OVERLAY,
    ENABLE_SEMANTIC_CHUNKING,
    SEMANTIC_THRESHOLD,
    MIN_CHUNK_SIZE,
    MAX_CHUNK_SIZE,
    ENABLE_PARENT_RETRIEVAL,
    PARENT_CHUNK_SIZE,
    ENABLE_METADATA_ENHANCEMENT,
)


def scan_documents() -> List[Dict]:
    """扫描知识库目录，返回文档列表"""
    documents = []

    if not os.path.exists(KNOWLEDGE_LIB_DIR):
        os.makedirs(KNOWLEDGE_LIB_DIR)
        return documents

    for root, dirs, files in os.walk(KNOWLEDGE_LIB_DIR):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in SUPPORTED_FORMATS:
                filepath = os.path.join(root, file)
                relpath = os.path.relpath(filepath, KNOWLEDGE_LIB_DIR)
                documents.append({
                    'filepath': filepath,
                    'filename': file,
                    'relpath': relpath,
                    'format': ext,
                    'mtime': os.path.getmtime(filepath)
                })

    return documents


def read_document(filepath: str, format: str) -> str:
    """读取文档内容"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # JSON 格式：提取关键信息
        if format == '.json':
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    lines = []
                    for key, value in data.items():
                        lines.append(f"{key}: {value}")
                    return '\n'.join(lines)
                elif isinstance(data, list):
                    return '\n'.join(str(item) for item in data)
                else:
                    return str(data)
            except json.JSONDecodeError:
                return content

        return content
    except Exception as e:
        return f"[读取错误: {str(e)}]"


def extract_title(content: str, source: str) -> str:
    """提取文档标题"""
    match = re.search(r'^#\s+(.+)', content, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return os.path.splitext(source)[0]


def split_into_sentences(text: str) -> List[str]:
    """将文本分割成句子（中英文混合）"""
    # 中文句号、英文句号、问号、感叹号、换行
    sentences = re.split(r'(?<=[。！？.!?])\s*|(?<=\n)', text)
    return [s.strip() for s in sentences if s.strip()]


def split_document_smart(content: str, source: str) -> List[Dict]:
    """智能分片：按 Markdown 标题/段落分片，保持语义完整性"""
    chunks = []
    doc_title = extract_title(content, source)

    # 按标题分割（Markdown ## 或 ###）
    sections = re.split(r'\n(?=##\s)', content)

    chunk_index = 0

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # 提取当前 section 的标题
        section_title_match = re.match(r'^##?\s+(.+)', section)
        section_title = section_title_match.group(1).strip() if section_title_match else doc_title

        # 如果 section 太长，按段落进一步分割
        if len(section) > CHUNK_SIZE:
            paragraphs = re.split(r'\n\n+', section)

            current_chunk = ""
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue

                if len(current_chunk) + len(para) + 2 <= CHUNK_SIZE:
                    current_chunk += "\n\n" + para if current_chunk else para
                else:
                    if current_chunk and len(current_chunk) >= MIN_CHUNK_SIZE:
                        chunks.append({
                            'content': current_chunk,
                            'source': source,
                            'section': section_title,
                            'index': chunk_index,
                            'doc_title': doc_title
                        })
                        chunk_index += 1

                    if len(para) > CHUNK_SIZE:
                        sentences = re.split(r'[。！？\n]', para)
                        sub_chunk = ""
                        for sent in sentences:
                            sent = sent.strip()
                            if not sent:
                                continue
                            if len(sub_chunk) + len(sent) + 1 <= CHUNK_SIZE:
                                sub_chunk += sent if not sub_chunk else sent
                            else:
                                if sub_chunk and len(sub_chunk) >= MIN_CHUNK_SIZE:
                                    chunks.append({
                                        'content': sub_chunk,
                                        'source': source,
                                        'section': section_title,
                                        'index': chunk_index,
                                        'doc_title': doc_title
                                    })
                                    chunk_index += 1
                                sub_chunk = sent
                        current_chunk = sub_chunk
                    else:
                        current_chunk = para

            if current_chunk and len(current_chunk) >= MIN_CHUNK_SIZE:
                chunks.append({
                    'content': current_chunk,
                    'source': source,
                    'section': section_title,
                    'index': chunk_index,
                    'doc_title': doc_title
                })
                chunk_index += 1
        else:
            if len(section) >= MIN_CHUNK_SIZE:
                chunks.append({
                    'content': section,
                    'source': source,
                    'section': section_title,
                    'index': chunk_index,
                    'doc_title': doc_title
                })
                chunk_index += 1

    # 添加重叠
    for i in range(len(chunks) - 1):
        next_content = chunks[i + 1]['content']
        overlay_text = next_content[:CHUNK_OVERLAY]
        if overlay_text and len(chunks[i]['content']) + len(overlay_text) <= MAX_CHUNK_SIZE:
            chunks[i]['content'] += "\n...[续]" + overlay_text

    return chunks


def split_document_semantic(content: str, source: str, embedding_model) -> List[Dict]:
    """语义分片：基于 embedding 相似度动态分割"""
    if not embedding_model:
        print("[RAG] 无 embedding 模型，回退到智能分片")
        return split_document_smart(content, source)

    chunks = []
    doc_title = extract_title(content, source)

    # 先按段落分割
    paragraphs = re.split(r'\n\n+', content)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if not paragraphs:
        return chunks

    # 获取段落的 embedding
    try:
        paragraph_embeddings = embedding_model.encode(paragraphs, show_progress_bar=False)
    except Exception as e:
        print(f"[RAG] Embedding 失败: {e}")
        return split_document_smart(content, source)

    import numpy as np
    from numpy.linalg import norm

    # 计算相邻段落的相似度
    similarities = []
    for i in range(len(paragraph_embeddings) - 1):
        sim = np.dot(paragraph_embeddings[i], paragraph_embeddings[i + 1]) / (
            norm(paragraph_embeddings[i]) * norm(paragraph_embeddings[i + 1])
        )
        similarities.append(sim)

    # 根据相似度分割
    current_chunk_paras = [paragraphs[0]]
    current_section = ""

    for i, sim in enumerate(similarities):
        current_para = paragraphs[i + 1]

        # 如果相似度低于阈值，或者当前块已经很长，则分割
        current_text = '\n\n'.join(current_chunk_paras)

        if sim < SEMANTIC_THRESHOLD or len(current_text) + len(current_para) > MAX_CHUNK_SIZE:
            if current_text and len(current_text) >= MIN_CHUNK_SIZE:
                # 提取 section 标题
                section_title = extract_section_title(current_text, doc_title)

                chunks.append({
                    'content': current_text,
                    'source': source,
                    'section': section_title,
                    'index': len(chunks),
                    'doc_title': doc_title,
                    'semantic_split': True,
                    'split_similarity': round(sim, 3) if sim < SEMANTIC_THRESHOLD else None
                })

            current_chunk_paras = [current_para]
        else:
            current_chunk_paras.append(current_para)

    # 处理最后一个块
    if current_chunk_paras:
        current_text = '\n\n'.join(current_chunk_paras)
        if len(current_text) >= MIN_CHUNK_SIZE:
            section_title = extract_section_title(current_text, doc_title)
            chunks.append({
                'content': current_text,
                'source': source,
                'section': section_title,
                'index': len(chunks),
                'doc_title': doc_title,
                'semantic_split': True
            })

    return chunks


def extract_section_title(text: str, doc_title: str) -> str:
    """从文本中提取 section 标题"""
    match = re.match(r'^##?\s+(.+)', text)
    if match:
        return match.group(1).strip()
    return doc_title


def create_parent_chunks(content: str, source: str) -> List[Dict]:
    """创建父文档块（更大的上下文块）"""
    parent_chunks = []
    doc_title = extract_title(content, source)

    # 按 Markdown 一级标题分割
    sections = re.split(r'\n(?=#\s)', content)

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # 如果 section 太长，进一步分割
        if len(section) > PARENT_CHUNK_SIZE:
            # 按二级标题分割
            subsections = re.split(r'\n(?=##\s)', section)

            current_parent = ""
            for subsec in subsections:
                subsec = subsec.strip()
                if not subsec:
                    continue

                if len(current_parent) + len(subsec) + 2 <= PARENT_CHUNK_SIZE:
                    current_parent += "\n\n" + subsec if current_parent else subsec
                else:
                    if current_parent:
                        section_title = extract_section_title(current_parent, doc_title)
                        parent_chunks.append({
                            'content': current_parent,
                            'source': source,
                            'section': section_title,
                            'doc_title': doc_title,
                            'chunk_type': 'parent'
                        })
                    current_parent = subsec

            if current_parent:
                section_title = extract_section_title(current_parent, doc_title)
                parent_chunks.append({
                    'content': current_parent,
                    'source': source,
                    'section': section_title,
                    'doc_title': doc_title,
                    'chunk_type': 'parent'
                })
        else:
            section_title = extract_section_title(section, doc_title)
            parent_chunks.append({
                'content': section,
                'source': source,
                'section': section_title,
                'doc_title': doc_title,
                'chunk_type': 'parent'
            })

    return parent_chunks


def extract_keywords_and_summary(content: str) -> Tuple[List[str], str]:
    """提取关键词和摘要（纯本地算法，零 LLM 调用）"""
    import jieba
    from collections import Counter

    # 本地关键词提取（TF-IDF 风格）
    words = jieba.lcut(content)
    stopwords = {
        '的', '是', '在', '了', '和', '与', '或', '等', '及', '对', '为', '以', '中',
        '上', '下', '到', '从', '被', '把', '让', '给', '向', '于', '这', '那', '有',
        '一个', '可以', '需要', '进行', '通过', '使用', '如', '时', '将', '会', '也'
    }

    # 过滤并提取关键词
    keywords = [w for w in words if len(w) >= 2 and w not in stopwords and not w.isspace() and not w.isdigit()]
    word_freq = Counter(keywords)
    top_keywords = [w for w, _ in word_freq.most_common(10)]

    # 本地摘要：提取关键句子
    sentences = re.split(r'[。！？\n]', content)
    sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) >= 20]

    # 选择包含最多关键词的句子作为摘要
    if sentences:
        scored_sentences = []
        for sent in sentences[:10]:  # 只检查前 10 个句子
            score = sum(1 for kw in top_keywords if kw in sent)
            scored_sentences.append((sent, score))
        scored_sentences.sort(key=lambda x: x[1], reverse=True)
        summary = scored_sentences[0][0] if scored_sentences else sentences[0]
        if len(summary) > 150:
            summary = summary[:150] + '...'
    else:
        summary = content[:150].replace('\n', ' ') + '...' if len(content) > 150 else content

    return top_keywords, summary


def extract_batch_keywords(documents: List[Dict], llm_client=None) -> Dict[str, Dict]:
    """批量提取关键词（一次 LLM 调用处理所有文档）"""
    result = {}

    if not llm_client:
        # 无 LLM，全部使用本地算法
        for doc in documents:
            content = read_document(doc['filepath'], doc['format'])
            if content and not content.startswith('[读取错误'):
                keywords, summary = extract_keywords_and_summary(content)
                result[doc['relpath']] = {
                    'keywords': keywords,
                    'summary': summary,
                    'doc_title': extract_title(content, doc['relpath'])
                }
        return result

    # 批量调用 LLM（一次处理所有文档）
    try:
        # 构建批量提示
        doc_contents = []
        for doc in documents[:20]:  # 最多处理 20 个文档，避免超长
            content = read_document(doc['filepath'], doc['format'])
            if content and not content.startswith('[读取错误'):
                # 截取每个文档的关键内容
                truncated = content[:800]
                doc_contents.append(f"【文档: {doc['relpath']}】\n{truncated}")

        if not doc_contents:
            return result

        batch_content = '\n\n---\n\n'.join(doc_contents)

        prompt = f"""请为以下文档提取关键词（每个文档提取 5 个关键词）。

{batch_content}

请按以下 JSON 格式输出：
{{"文档路径1": ["关键词1", "关键词2", ...], "文档路径2": [...], ...}}
只输出关键词，不需要摘要。
"""
        from .config import DEFAULT_MODEL
        response = llm_client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.3
        )
        result_text = response.choices[0].message.content.strip()

        # 解析 JSON
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if json_match:
            keywords_map = json.loads(json_match.group())

            # 合并本地摘要 + LLM 关键词
            for doc in documents:
                relpath = doc['relpath']
                content = read_document(doc['filepath'], doc['format'])

                # 使用 LLM 关键词，本地摘要
                keywords = keywords_map.get(relpath, [])
                _, summary = extract_keywords_and_summary(content)  # 本地摘要

                result[relpath] = {
                    'keywords': keywords,
                    'summary': summary,
                    'doc_title': extract_title(content, relpath) if content else relpath
                }
        else:
            # 解析失败，全部本地
            for doc in documents:
                content = read_document(doc['filepath'], doc['format'])
                if content:
                    keywords, summary = extract_keywords_and_summary(content)
                    result[doc['relpath']] = {
                        'keywords': keywords,
                        'summary': summary,
                        'doc_title': extract_title(content, doc['relpath'])
                    }

        print(f"[RAG] 批量提取完成，处理 {len(result)} 个文档（1 次 LLM 调用）")

    except Exception as e:
        print(f"[RAG] 批量提取失败，回退到本地算法: {e}")
        for doc in documents:
            content = read_document(doc['filepath'], doc['format'])
            if content and not content.startswith('[读取错误'):
                keywords, summary = extract_keywords_and_summary(content)
                result[doc['relpath']] = {
                    'keywords': keywords,
                    'summary': summary,
                    'doc_title': extract_title(content, doc['relpath'])
                }

    return result


def process_all_documents(embedding_model=None, llm_client=None) -> tuple:
    """处理所有文档，返回 (分片列表, 统计信息)

    Returns:
        tuple: (chunks, stats)
            - chunks: 分片列表
            - stats: {'scanned': int, 'read_failed': int, 'empty_content': int, 'no_chunks': int, 'success': int}
    """
    all_chunks = []
    all_parent_chunks = []

    documents = scan_documents()
    scanned_count = len(documents)
    print(f"[RAG] 扫描到 {scanned_count} 个文档")

    # 统计信息
    stats = {
        'scanned': scanned_count,
        'read_failed': 0,
        'empty_content': 0,
        'no_chunks': 0,
        'success': 0
    }

    # 批量提取关键词（一次 LLM 调用或纯本地算法）
    doc_metadata_cache = {}
    if ENABLE_METADATA_ENHANCEMENT:
        doc_metadata_cache = extract_batch_keywords(documents, llm_client)

    for doc in documents:
        content = read_document(doc['filepath'], doc['format'])
        if not content:
            stats['empty_content'] += 1
            continue
        if content.startswith('[读取错误'):
            stats['read_failed'] += 1
            continue

        # 选择分片策略
        if ENABLE_SEMANTIC_CHUNKING and embedding_model:
            chunks = split_document_semantic(content, doc['relpath'], embedding_model)
        else:
            chunks = split_document_smart(content, doc['relpath'])

        if not chunks:
            stats['no_chunks'] += 1
            continue

        stats['success'] += 1

        # 获取文档级元数据
        doc_meta = doc_metadata_cache.get(doc['relpath'], {})

        # 为每个分片添加元数据（继承文档级关键词）
        for chunk in chunks:
            chunk['doc_mtime'] = doc['mtime']
            chunk['doc_format'] = doc['format']

            # 元数据增强：使用文档级关键词（不再对每个分片调用 LLM）
            if ENABLE_METADATA_ENHANCEMENT:
                chunk['keywords'] = doc_meta.get('keywords', [])
                chunk['summary'] = doc_meta.get('summary', '')
                chunk['doc_title'] = doc_meta.get('doc_title', '')

            all_chunks.append(chunk)

        # 创建父文档块
        if ENABLE_PARENT_RETRIEVAL:
            parent_chunks = create_parent_chunks(content, doc['relpath'])
            for pc in parent_chunks:
                pc['doc_mtime'] = doc['mtime']
                pc['doc_format'] = doc['format']
                # 为父块建立到子块的映射
                pc['child_indices'] = []
                for i, child in enumerate(chunks):
                    if child['content'] in pc['content'] or pc['content'] in child['content']:
                        pc['child_indices'].append(i)
            all_parent_chunks.extend(parent_chunks)

    # 存储父文档块到全局变量（用于检索时扩展上下文）
    global _parent_chunks_store
    _parent_chunks_store = all_parent_chunks

    print(f"[RAG] 生成 {len(all_chunks)} 个分片，成功处理 {stats['success']}/{scanned_count} 个文档")
    if stats['empty_content'] > 0:
        print(f"[RAG] 空内容文档: {stats['empty_content']}")
    if stats['no_chunks'] > 0:
        print(f"[RAG] 无分片文档: {stats['no_chunks']}")
    if stats['read_failed'] > 0:
        print(f"[RAG] 读取失败文档: {stats['read_failed']}")
    if all_parent_chunks:
        print(f"[RAG] 生成 {len(all_parent_chunks)} 个父文档块")

    return all_chunks, stats


# 全局父文档块存储
_parent_chunks_store: List[Dict] = []


def get_parent_chunk(child_chunk: Dict) -> Optional[Dict]:
    """获取子块对应的父文档块"""
    global _parent_chunks_store

    if not _parent_chunks_store:
        return None

    child_content = child_chunk.get('content', '')
    child_source = child_chunk.get('source', '')

    # 查找包含该子块的父块
    best_parent = None
    best_overlap = 0

    for parent in _parent_chunks_store:
        if parent.get('source') == child_source:
            # 计算重叠度
            overlap = len(set(child_content) & set(parent.get('content', '')))
            if overlap > best_overlap:
                best_overlap = overlap
                best_parent = parent

    return best_parent


def get_document_list() -> List[Dict]:
    """获取文档列表（用于前端展示）"""
    documents = scan_documents()
    result = []

    for doc in documents:
        content = read_document(doc['filepath'], doc['format'])
        result.append({
            'filename': doc['filename'],
            'relpath': doc['relpath'],
            'format': doc['format'],
            'size': len(content),
            'mtime': doc['mtime']
        })

    return result


def get_library_mtime() -> float:
    """获取知识库最后修改时间"""
    latest_mtime = 0

    if not os.path.exists(KNOWLEDGE_LIB_DIR):
        return 0

    for root, dirs, files in os.walk(KNOWLEDGE_LIB_DIR):
        for file in files:
            filepath = os.path.join(root, file)
            mtime = os.path.getmtime(filepath)
            if mtime > latest_mtime:
                latest_mtime = mtime

    return latest_mtime