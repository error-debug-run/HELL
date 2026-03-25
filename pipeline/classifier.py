# hell/pipeline/classifier.py

import re
import math
import numpy as np
from collections import defaultdict
from pathlib import Path


# ─────────────────────────────────────────────
# NLP UTILITIES — kept for TFIDFEngine fallback
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
    text   = text.lower()
    text   = re.sub(r"[^a-z0-9\s]", "", text)
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
# TF-IDF ENGINE — kept as fallback
# ─────────────────────────────────────────────

class TFIDFEngine:
    def __init__(self):
        self.vocab       = {}
        self.idf         = {}
        self.doc_vectors = []
        self.labels      = []

    def fit(self, dataset):
        docs        = [get_features(text) for text, _ in dataset]
        self.labels = [label for _, label in dataset]
        N           = len(docs)

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

# ─────────────────────────────────────────────
# MINILM ENGINE — semantic understanding
# ─────────────────────────────────────────────

MINILM_PATH = Path(__file__).parent.parent / "models" / "minilm"

class MiniLMEngine:
    """
    Drop-in replacement for TFIDFEngine.
    Same fit() and predict() interface.
    Uses semantic embeddings instead of keyword matching.
    Understands synonyms — "terminate spotify" → close_app
    Runs on CPU, ~5-10ms per inference.
    """

    def __init__(self):
        self.model            = None
        self.train_texts      = []
        self.train_labels     = []
        self.train_embeddings = None
        self._loaded          = False

    def load(self, model_path=None):
        """
        Load MiniLM model from local path.
        Call once before fit().
        """
        from sentence_transformers import SentenceTransformer

        path = str(model_path or MINILM_PATH)
        print(f"  loading MiniLM from: {path}")
        self.model   = SentenceTransformer(path)
        self._loaded = True
        print(f"  MiniLM ready")

    def fit(self, dataset):
        """
        Encode all training examples.
        Same signature as TFIDFEngine.fit().
        """
        if not self._loaded:
            raise RuntimeError(
                "Call load() before fit(). "
                "Download model with: "
                "MiniLMEngine.download()"
            )

        self.train_texts  = [text  for text, _  in dataset]
        self.train_labels = [label for _,    label in dataset]

        print(f"  encoding {len(self.train_texts)} training examples...")
        self.train_embeddings = self.model.encode(
            self.train_texts,
            convert_to_numpy    = True,
            show_progress_bar   = False,
            batch_size          = 32,
        )
        print(f"  training complete")

    def predict(self, text, top_n=3):
        """
        Predict intent from text.
        Same signature as TFIDFEngine.predict().
        Returns (intent, confidence_percent).
        """
        if self.train_embeddings is None:
            return "unknown", 0.0

        # encode query
        query_vec = self.model.encode(
            [text],
            convert_to_numpy  = True,
            show_progress_bar = False,
        )[0]

        # cosine similarity against all training examples
        norms  = np.linalg.norm(self.train_embeddings, axis=1)
        q_norm = np.linalg.norm(query_vec)

        if q_norm == 0:
            return "unknown", 0.0

        sims = self.train_embeddings @ query_vec / (norms * q_norm + 1e-9)

        # vote among top_n
        top_idx = np.argsort(sims)[::-1][:top_n]
        vote    = defaultdict(float)
        for idx in top_idx:
            vote[self.train_labels[idx]] += float(sims[idx])

        if not vote:
            return "unknown", 0.0

        best       = max(vote, key=vote.get)
        total      = sum(vote.values())
        confidence = vote[best] / (total + 1e-9) * 100

        return best, round(confidence, 1)

    @staticmethod
    def download(save_path=None):
        """
        Download MiniLM model from HuggingFace and save locally.
        Run once — fully offline after this.
        """
        from sentence_transformers import SentenceTransformer

        path = str(save_path or MINILM_PATH)
        print(f"  downloading all-MiniLM-L6-v2 to: {path}")
        model = SentenceTransformer("all-MiniLM-L6-v2")
        model.save(path)
        print(f"  saved to {path}")
        print(f"  model is now offline-ready")