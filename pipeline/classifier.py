# hell/pipeline/classifier.py

import re
import math
from collections import defaultdict

# ─────────────────────────────────────────────
# NLP UTILITIES
# ─────────────────────────────────────────────

STOPWORDS = {
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it",
    "is", "am", "are", "was", "were", "be", "been", "being",
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "up", "about", "into",
    "can", "could", "would", "should", "will", "do", "does", "did",
    "this", "that", "these", "those", "there", "some", "any",
    "please", "just", "very", "so", "if", "then", "than",
}

def preprocess(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    tokens = text.split()
    tokens = [t for t in tokens if t not in STOPWORDS and len(t) > 1]
    return tokens

def get_ngrams(tokens, n=2):
    return [" ".join(tokens[i:i+n]) for i in range(len(tokens)-n+1)]

def get_features(text):
    tokens   = preprocess(text)
    bigrams  = get_ngrams(tokens, 2)
    trigrams = get_ngrams(tokens, 3)
    return tokens + bigrams + trigrams

# ─────────────────────────────────────────────
# TF-IDF ENGINE
# ─────────────────────────────────────────────

class TFIDFEngine:
    def __init__(self):
        self.vocab       = {}
        self.idf         = {}
        self.doc_vectors = []
        self.labels      = []

    def fit(self, dataset):
        docs         = [get_features(text) for text, _ in dataset]
        self.labels  = [label for _, label in dataset]
        N            = len(docs)

        df = defaultdict(int)
        for doc in docs:
            for term in set(doc):
                df[term] += 1

        self.vocab = {term: i for i, term in enumerate(df.keys())}
        self.idf   = {term: math.log(N / (df[term] + 1)) for term in df}

        self.doc_vectors = []
        for doc in docs:
            self.doc_vectors.append(self._vectorize(doc))

    def _vectorize(self, tokens):
        tf    = defaultdict(float)
        for t in tokens:
            tf[t] += 1
        total = len(tokens) if tokens else 1
        vec   = {}
        for term, count in tf.items():
            if term in self.idf:
                vec[term] = (count / total) * self.idf[term]
        return vec

    def _cosine(self, v1, v2):
        common = set(v1) & set(v2)
        dot    = sum(v1[t] * v2[t] for t in common)
        mag1   = math.sqrt(sum(x**2 for x in v1.values()))
        mag2   = math.sqrt(sum(x**2 for x in v2.values()))
        if mag1 == 0 or mag2 == 0:
            return 0.0
        return dot / (mag1 * mag2)

    def predict(self, text, top_n=3):
        tokens    = get_features(text)
        query_vec = self._vectorize(tokens)

        scores = []
        for i, doc_vec in enumerate(self.doc_vectors):
            score = self._cosine(query_vec, doc_vec)
            scores.append((score, self.labels[i]))

        scores.sort(reverse=True)

        vote = defaultdict(float)
        for score, label in scores[:top_n]:
            vote[label] += score

        if not vote:
            return "unknown", 0.0

        best       = max(vote, key=vote.get)
        confidence = vote[best] / (sum(vote.values()) + 1e-9)
        return best, round(confidence * 100, 1)