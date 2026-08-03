"""RAG 评估模块：实时评估召回和重排效果"""

import math
from typing import List, Dict


class RAGEvaluator:
    """RAG 实时评估器"""

    def evaluate_retrieval(self, chunks: List[Dict]) -> Dict:
        """评估召回结果"""
        if not chunks:
            return {
                'count': 0,
                'avg_score': 0,
                'score_distribution': {},
                'retrieval_types': {},
                'bm25_hit': False,
                'vector_hit': False
            }

        # 计算平均分数
        scores = [c.get('final_score', c.get('score', 0)) for c in chunks]
        avg_score = sum(scores) / len(scores) if scores else 0

        # 分数分布（高分/中分/低分）
        high_score = len([s for s in scores if s >= 0.7])
        mid_score = len([s for s in scores if 0.4 <= s < 0.7])
        low_score = len([s for s in scores if s < 0.4])

        # 检索类型分布
        retrieval_types = {}
        for c in chunks:
            type_name = c.get('retrieval_type', 'vector')
            retrieval_types[type_name] = retrieval_types.get(type_name, 0) + 1

        # BM25 和向量是否都有命中
        bm25_hit = retrieval_types.get('bm25', 0) > 0 or retrieval_types.get('hybrid', 0) > 0
        vector_hit = retrieval_types.get('vector', 0) > 0 or retrieval_types.get('hybrid', 0) > 0

        return {
            'count': len(chunks),
            'avg_score': round(avg_score, 4),
            'max_score': round(max(scores), 4),
            'min_score': round(min(scores), 4),
            'score_distribution': {
                'high': high_score,    # >= 0.7
                'medium': mid_score,   # 0.4-0.7
                'low': low_score       # < 0.4
            },
            'retrieval_types': retrieval_types,
            'bm25_hit': bm25_hit,
            'vector_hit': vector_hit,
            'hybrid_rate': round(retrieval_types.get('hybrid', 0) / len(chunks), 2) if chunks else 0
        }

    def evaluate_rerank(self, before_chunks: List[Dict], after_chunks: List[Dict]) -> Dict:
        """评估重排效果"""
        if not before_chunks or not after_chunks:
            return {
                'count': 0,
                'score_improvement': 0,
                'top_changed': False
            }

        # 重排前的分数（按 index 排序）
        before_scores = {}
        for c in before_chunks:
            before_scores[c.get('id', c.get('index', 0))] = c.get('final_score', c.get('score', 0))

        # 重排后的分数
        after_scores = [c.get('rerank_score', c.get('final_score', c.get('score', 0))) for c in after_chunks]

        # 检查第一名是否变化
        before_top_id = before_chunks[0].get('id', before_chunks[0].get('index', 0))
        after_top_id = after_chunks[0].get('id', after_chunks[0].get('index', 0))
        top_changed = before_top_id != after_top_id

        # 重排分数统计
        avg_rerank_score = sum(after_scores) / len(after_scores) if after_scores else 0

        # 计算位置变化
        position_changes = []
        for i, c in enumerate(after_chunks):
            original_index = c.get('index', 0)
            new_index = i + 1
            change = original_index - new_index
            position_changes.append({
                'id': c.get('id'),
                'original': original_index,
                'new': new_index,
                'change': change  # 正数表示上升，负数表示下降
            })

        # 平均位置变化幅度
        avg_change = sum(abs(p['change']) for p in position_changes) / len(position_changes) if position_changes else 0

        return {
            'count': len(after_chunks),
            'avg_rerank_score': round(avg_rerank_score, 1),
            'max_rerank_score': max(after_scores) if after_scores else 0,
            'min_rerank_score': min(after_scores) if after_scores else 0,
            'top_changed': top_changed,
            'avg_position_change': round(avg_change, 1),
            'position_changes': position_changes
        }

    def calculate_ndcg(self, chunks: List[Dict], relevance_scores: List[float], k: int = 3) -> Dict:
        """计算 NDCG（如果有人工标注的相关性）"""
        if not relevance_scores or len(relevance_scores) < k:
            return {'ndcg': 0, 'dcg': 0, 'idcg': 0}

        def dcg(scores, k):
            return sum(score / math.log2(i + 2) for i, score in enumerate(scores[:k]))

        actual_scores = relevance_scores[:k]
        ideal_scores = sorted(relevance_scores, reverse=True)[:k]

        dcg_value = dcg(actual_scores, k)
        idcg_value = dcg(ideal_scores, k)
        ndcg = dcg_value / idcg_value if idcg_value > 0 else 0

        return {
            'ndcg': round(ndcg, 4),
            'dcg': round(dcg_value, 4),
            'idcg': round(idcg_value, 4)
        }

    def full_evaluation(self, retrieved: List[Dict], reranked: List[Dict], answer: str) -> Dict:
        """完整评估"""
        retrieval_eval = self.evaluate_retrieval(retrieved)
        rerank_eval = self.evaluate_rerank(retrieved, reranked)

        # 答案评估（简单指标）
        answer_eval = {
            'length': len(answer),
            'has_content': len(answer) > 10,
            'has_error': '失败' in answer or '错误' in answer
        }

        return {
            'retrieval': retrieval_eval,
            'rerank': rerank_eval,
            'answer': answer_eval,
            'overall_quality': self._calculate_overall_quality(retrieval_eval, rerank_eval)
        }

    def _calculate_overall_quality(self, retrieval_eval: Dict, rerank_eval: Dict) -> Dict:
        """计算整体质量评分"""
        # 召回质量：基于平均分数和类型覆盖
        retrieval_score = 0
        if retrieval_eval['avg_score'] >= 0.6:
            retrieval_score = 80
        elif retrieval_eval['avg_score'] >= 0.4:
            retrieval_score = 60
        else:
            retrieval_score = 40

        # 混合检索加分
        if retrieval_eval['bm25_hit'] and retrieval_eval['vector_hit']:
            retrieval_score += 10

        # 重排质量：基于分数分布
        rerank_score = 0
        if rerank_eval['avg_rerank_score'] >= 70:
            rerank_score = 80
        elif rerank_eval['avg_rerank_score'] >= 50:
            rerank_score = 60
        else:
            rerank_score = 40

        overall = (retrieval_score + rerank_score) / 2

        return {
            'score': round(overall, 1),
            'retrieval_score': retrieval_score,
            'rerank_score': rerank_score,
            'grade': self._get_grade(overall)
        }

    def _get_grade(self, score: float) -> str:
        """获取等级"""
        if score >= 80:
            return '优秀'
        elif score >= 60:
            return '良好'
        elif score >= 40:
            return '一般'
        else:
            return '较差'