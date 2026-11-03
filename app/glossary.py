"""군 용어사전. 승인된(approved) 대응어만 검색 확장에 쓴다."""
from .textutil import tokens


class Glossary:
    def __init__(self, data):
        self.version = data.get("version", "glossary-unknown")
        self.groups = [g for g in data.get("groups", []) if g.get("approved") is True]
        self.unapproved = [g for g in data.get("groups", []) if g.get("approved") is not True]
        self._related = {}
        for pair in data.get("related_domains", []):
            for a in pair:
                self._related.setdefault(a, set()).update(b for b in pair if b != a)
        self._tok_to_groups = {}
        for g in self.groups:
            for term in [g["canonical"]] + g.get("synonyms", []):
                for t in tokens(term):
                    self._tok_to_groups.setdefault(t, []).append(g)

    def expand(self, toks, synonym_weight=0.5, domain_term_weight=1.0):
        """질의 토큰 → {용어: 가중치}.

        대표어는 모든 대응어로 넓히고, 대응어는 대표어로만 넓힌다(대응어끼리 퍼지지 않게).
        분야를 가리키는 용어는 조건 일치도에서 따로 반영하므로 domain_term_weight 로 낮춘다.
        """
        weights = {}
        for t in toks:
            groups = self._tok_to_groups.get(t, [])
            w = domain_term_weight if any(g.get("domain") for g in groups) else 1.0
            weights[t] = max(weights.get(t, 0), w)
        for t in toks:
            for g in self._tok_to_groups.get(t, []):
                is_canonical = t in tokens(g["canonical"])
                terms = [g["canonical"]] + (g.get("synonyms", []) if is_canonical else [])
                base = domain_term_weight if g.get("domain") else 1.0
                for term in terms:
                    for st in tokens(term):
                        if st not in weights:
                            weights[st] = synonym_weight * base
        return weights

    def related(self, domains):
        """서로 겹치는 분야(예: 보급과 군수). 질의 분야와 가까운 카탈로그를 '다른 분야'로 보지 않는 데 쓴다."""
        out = set()
        for d in domains:
            out |= self._related.get(d, set())
        return out - set(domains)

    def domains_in(self, text):
        qtoks = tokens(text)
        found = []
        for g in self.groups:
            dom = g.get("domain")
            if not dom or dom in found:
                continue
            if any(_term_in(t, qtoks) for t in [g["canonical"]] + g.get("synonyms", [])):
                found.append(dom)
        return found


def _term_in(term, qtoks):
    """용어가 질의에 낱말로 들어 있는가.

    질의 낱말이 용어와 같거나 용어로 시작하면 일치로 본다(차량정비 → 차량).
    낱말 끝에 붙은 경우는 세 글자 이상 용어만 인정한다(무선통신장비 → 통신장비).
    두 글자 용어가 다른 낱말 속에 들어 있는 경우는 일치로 보지 않는다(토지피복 ≠ 피복).
    """
    tt = tokens(term)
    if not tt:
        return False
    if len(tt) > 1:
        n = len(tt)
        return any(qtoks[i:i + n] == tt for i in range(len(qtoks) - n + 1))
    t = tt[0]
    return any(q == t or q.startswith(t) or (len(t) >= 3 and q.endswith(t)) for q in qtoks)
