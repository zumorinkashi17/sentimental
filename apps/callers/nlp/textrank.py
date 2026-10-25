"""TextRank extractive summarisation for call transcripts.

Implements the standard sentence-similarity TextRank graph with a light
term-frequency prior. Pure Python so no extra graph/ML dependency is needed
at inference time.
"""

from __future__ import annotations

import math
import re
from collections import Counter

_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9']+")

STOPWORDS = {
    # English
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "if",
    "then",
    "so",
    "to",
    "of",
    "in",
    "on",
    "at",
    "for",
    "with",
    "from",
    "by",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "am",
    "i",
    "you",
    "he",
    "she",
    "it",
    "we",
    "they",
    "me",
    "him",
    "her",
    "us",
    "them",
    "my",
    "your",
    "his",
    "its",
    "our",
    "their",
    "this",
    "that",
    "these",
    "those",
    "there",
    "here",
    "what",
    "which",
    "who",
    "whom",
    "when",
    "where",
    "why",
    "how",
    "not",
    "no",
    "yes",
    "do",
    "does",
    "did",
    "have",
    "has",
    "had",
    "can",
    "could",
    "will",
    "would",
    "should",
    "may",
    "might",
    "just",
    "very",
    "really",
    "about",
    "also",
    "as",
    "than",
    "too",
    "up",
    "out",
    "now",
    "still",
    "even",
    "like",
    "get",
    "got",
    "know",
    "think",
    "want",
    "going",
    "gonna",
    # Cebuano / Bisaya
    "ang",
    "nga",
    "ng",
    "sa",
    "si",
    "ni",
    "ko",
    "ka",
    "mo",
    "siya",
    "kami",
    "mi",
    "kita",
    "ta",
    "mga",
    "na",
    "pa",
    "man",
    "gud",
    "gyud",
    "jud",
    "lang",
    "ra",
    "og",
    "ug",
    "kay",
    "mao",
    "naa",
    "wala",
    "wa",
    "dili",
    "di",
    "kaayo",
    "pero",
    "aron",
    "karon",
    "dinhi",
    "diri",
    "didto",
    "unsa",
    "kinsa",
    "asa",
    "kanus-a",
    "ngano",
    "ma'am",
    "maam",
    "sir",
    "miss",
    "kuya",
    "ate",
    "miss",
    "po",
    "opo",
    "oo",
    "sige",
    "salamat",
    "hello",
    "hi",
    "goodnight",
    "lagi",
    "raba",
    "bitaw",
    "hinuon",
    "unta",
    "akong",
    "among",
    "inyong",
    "iyang",
    "ilang",
    "pangalan",
    "tawag",
    "suwayan",
    "hangtod",
    "daw",
    "ba",
    "pud",
    "pod",
    "sad",
    "usa",
    "duha",
    "tulo",
    "naa",
    "adunay",
    "walay",
    "kadtong",
    "kini",
    "kana",
    "kanang",
    "maong",
    "mao",
    "bisan",
    "basta",
    "unya",
    "dayon",
    "gihapon",
    "lamang",
    "ngano",
    "kanako",
    "nako",
    "nimo",
    "niya",
    "namo",
    "ninyo",
    "nila",
}


def split_sentences(text: str) -> list[str]:
    """Split a transcript into candidate summary sentences."""
    text = re.sub(r"\n+", " ", str(text or ""))
    parts = re.split(r"(?<=[.!?])(?<!\.[.!?])\s+", text)
    sentences = []
    for part in parts:
        cleaned = re.sub(r"\s+", " ", part).strip()
        if cleaned:
            sentences.append(cleaned)
    return sentences


def tokenize(sentence: str) -> list[str]:
    return [
        word.lower()
        for word in _WORD_RE.findall(sentence)
        if len(word) > 1 and word.lower() not in STOPWORDS
    ]


def _similarity(left: list[str], right: list[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    union = left_set | right_set
    return len(left_set & right_set) / len(union)


def _pagerank(matrix: list[list[float]], damping: float = 0.85, iterations: int = 60) -> list[float]:
    count = len(matrix)
    if count == 0:
        return []
    scores = [1.0 / count] * count
    for _ in range(iterations):
        updated = []
        for column in range(count):
            incoming = 0.0
            for row in range(count):
                outgoing = sum(matrix[row])
                if outgoing:
                    incoming += matrix[row][column] / outgoing * scores[row]
            updated.append((1.0 - damping) / count + damping * incoming)
        scores = updated
    return scores


def summarize(text: str, max_sentences: int = 4, min_words: int = 4) -> str:
    """Return the top-ranked sentences in their original order."""
    sentences = split_sentences(text)
    if not sentences:
        return ""

    tokenized = [tokenize(sentence) for sentence in sentences]
    eligible = [
        index
        for index, tokens in enumerate(tokenized)
        if len(tokens) >= min_words
    ]
    if not eligible:
        eligible = [index for index, tokens in enumerate(tokenized) if tokens]
    if not eligible:
        return ""

    selected_sentences = [sentences[index] for index in eligible]
    selected_tokens = [tokenized[index] for index in eligible]
    count = len(selected_sentences)

    matrix = [[0.0] * count for _ in range(count)]
    for row in range(count):
        for column in range(row + 1, count):
            weight = _similarity(selected_tokens[row], selected_tokens[column])
            matrix[row][column] = weight
            matrix[column][row] = weight

    scores = _pagerank(matrix)

    frequencies = Counter()
    for tokens in selected_tokens:
        frequencies.update(tokens)
    total = sum(frequencies.values()) or 1
    tf_prior = {word: count / total for word, count in frequencies.items()}

    ranked = []
    for index, (sentence, tokens, score) in enumerate(
        zip(selected_sentences, selected_tokens, scores)
    ):
        if tokens:
            tf_score = sum(tf_prior.get(token, 0.0) for token in tokens) / len(tokens)
        else:
            tf_score = 0.0
        ranked.append((score + 0.25 * tf_score, index, sentence))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    top = sorted(ranked[: max(1, max_sentences)], key=lambda item: item[1])
    return " ".join(sentence for _, _, sentence in top).strip()
