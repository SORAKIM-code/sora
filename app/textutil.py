"""텍스트 정규화와 토큰화.

형태소 분석기 없이 조사·어미를 한 번 떼어 내는 단순 규칙을 쓴다.
문서와 질의에 같은 규칙을 적용하므로 일관성은 유지된다.
"""
import re
import unicodedata

# '1종'·'9종' 같은 보급 분류는 한 낱말로 본다.
_WORD_RE = re.compile(r"\d+종|[0-9a-z]+|[가-힣]+")

_SUFFIXES = sorted([
    "에서의", "으로서", "으로써", "에게서", "으로는", "에서는", "이라는", "하고자", "하려고",
    "하려는", "하는데", "해서는", "에서", "에게", "으로", "부터", "까지", "처럼", "보다",
    "이나", "하고", "하는", "하여", "해서", "했던", "되는", "되어", "와의", "과의",
    "된", "한", "할", "의", "은", "는", "이", "가", "을", "를", "에", "와", "과",
    "도", "로", "만", "별", "들",
], key=len, reverse=True)

STOPWORDS = {
    "싶다", "싶습니다", "싶어", "싶은", "싶어요", "하다", "합니다", "있다", "있는", "있을", "있나요",
    "대한", "위한", "위해", "관련", "통해", "또는", "그리고", "데이터", "자료", "연구", "원합니다",
    "필요", "필요합니다", "어떤", "무엇", "가능", "가능한지", "알고", "보고", "하기", "에서",
    "이용", "활용", "찾고", "찾아", "주세요", "있으면", "the", "and", "for", "of",
}

INJECTION_PATTERNS = [
    re.compile(r"(이전|위의|앞의|모든)\s*(지시|명령|규칙|지침).{0,12}(무시|잊)"),
    re.compile(r"ignore\s+(all|any|previous|prior|the)"),
    re.compile(r"system\s*prompt|시스템\s*프롬프트|개발자\s*모드|jailbreak"),
    re.compile(r"권한.{0,8}(무시|우회|해제|상관없이)"),
    re.compile(r"(제한|비공개|모든|전체)\s*(카탈로그|자료|목록).{0,12}(출력|보여|나열|알려)"),
]


def normalize(text):
    return unicodedata.normalize("NFKC", text or "").lower()


def _strip(word):
    if not ("가" <= word[0] <= "힣"):
        return word
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 2:
            return word[: -len(suf)]
    return word


def tokens(text):
    out = []
    for w in _WORD_RE.findall(normalize(text)):
        w = _strip(w)
        if len(w) < 2 or w in STOPWORDS:
            continue
        out.append(w)
    return out


def char_ngrams(toks, sizes=(2, 3)):
    grams = []
    for t in toks:
        for n in sizes:
            if len(t) >= n:
                grams.extend(t[i:i + n] for i in range(len(t) - n + 1))
    return grams


def injection_flags(text):
    norm = normalize(text)
    return [p.pattern for p in INJECTION_PATTERNS if p.search(norm)]
