"""군 용어사전. 승인된(approved) 대응어만 검색 확장에 쓴다."""
from .textutil import normalize, tokens


class Glossary:
    def __init__(self, data):
        self.version = data.get("version", "glossary-unknown")
        self.groups = [g for g in data.get("groups", []) if g.get("approved") is True]
        self.unapproved = [g for g in data.get("groups", []) if g.get("approved") is not True]
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

    def domains_in(self, text):
        norm = normalize(text)
        found = []
        for g in self.groups:
            dom = g.get("domain")
            if not dom or dom in found:
                continue
            if any(normalize(t) in norm for t in [g["canonical"]] + g.get("synonyms", [])):
                found.append(dom)
        return found
