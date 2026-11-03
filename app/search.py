"""검색 인덱스: 키워드(BM25) + 의미 검색.

의미 검색은 시제품 단계에서 문자 n-gram TF-IDF 벡터와 승인 용어사전 확장으로 대신한다.
임베딩 모델이 승인되면 `SemanticEncoder` 를 교체하면 된다.

인덱스는 항상 '권한 내 문서'만으로 만든다. 권한 밖 문서가 IDF·벡터 통계에 섞이지 않게 해서
점수를 통한 존재 추론도 막는다(PRD 8장 권한 필터 적용 범위).
"""
import math
from collections import Counter

from .schema import SEARCH_FIELDS, value_text
from .textutil import char_ngrams, tokens

INDEX_VERSION = "hybrid-bm25-charngram-v1"


class SemanticEncoder:
    version = "char-ngram-tfidf-v1"

    def fit(self, doc_token_lists):
        df = Counter()
        grams = []
        for toks in doc_token_lists:
            c = Counter(char_ngrams(toks))
            grams.append(c)
            df.update(c.keys())
        n = len(doc_token_lists)
        self.n = n
        self.idf = {g: math.log((n + 1) / (d + 1)) + 1 for g, d in df.items()}
        self.vecs = [self._norm({g: tf * self.idf[g] for g, tf in c.items()}) for c in grams]

    def _norm(self, vec):
        s = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {k: v / s for k, v in vec.items()}

    def encode_query(self, weighted_terms):
        unseen = math.log(self.n + 1) + 1
        vec = Counter()
        for term, w in weighted_terms.items():
            for g in char_ngrams([term]):
                vec[g] += w * self.idf.get(g, unseen)
        return self._norm(vec)

    def similarities(self, qvec):
        return [sum(qvec.get(g, 0) * v for g, v in dv.items()) if qvec else 0.0 for dv in self.vecs]


class SearchIndex:
    def __init__(self, docs, k1=1.2, b=0.75):
        """docs: [{"id", "version", "values"}] — 이미 권한 필터를 거친 문서만 넘긴다."""
        self.docs = docs
        self.k1, self.b = k1, b
        self.tf, self.field_tokens, self.lens = [], [], []
        df = Counter()
        sem_tokens = []
        for d in docs:
            c, ft, st = Counter(), {}, []
            for key, w in SEARCH_FIELDS:
                toks = tokens(value_text(d["values"].get(key)))
                ft[key] = set(toks)
                for t in toks:
                    c[t] += w
                st.extend(toks * (2 if key == "title" else 1))
            self.tf.append(c)
            self.field_tokens.append(ft)
            self.lens.append(sum(c.values()))
            df.update(c.keys())
            sem_tokens.append(st)
        n = len(docs)
        self.avglen = (sum(self.lens) / n) if n else 1.0
        self.idf = {t: math.log(1 + (n - m + 0.5) / (m + 0.5)) for t, m in df.items()}
        self.encoder = SemanticEncoder()
        self.encoder.fit(sem_tokens)

    def keyword(self, weighted_terms):
        """문서별 (BM25 점수, {항목: [일치 용어]})."""
        out = []
        for i in range(len(self.docs)):
            tf, ln = self.tf[i], self.lens[i]
            score = 0.0
            matched = {}
            for term, qw in weighted_terms.items():
                f = tf.get(term)
                if not f:
                    continue
                idf = self.idf.get(term, 0)
                score += qw * idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * ln / self.avglen))
                for key, toks in self.field_tokens[i].items():
                    if term in toks:
                        matched.setdefault(key, []).append(term)
            out.append((score, matched))
        return out

    def semantic(self, weighted_terms):
        return self.encoder.similarities(self.encoder.encode_query(weighted_terms))

    def titles(self):
        return [(d["id"], d["values"].get("title") or "", d["values"].get("keywords") or []) for d in self.docs]
