# src/jarvis/localspeech/wakeword/mlp.py
"""Stage 2's small dense network, in NumPy (R5.2 row 83): standardised 16 x 96 windows ->
ReLU layers -> one sigmoid score, trained with Adam on class-weighted binary cross-entropy
(false wakes cost more than a miss). `dense()` folds the standardisation into the first layer
and gives PyTorch's [out][in] layout for `onnx_write.mlp_onnx`; `runner()` is the same maths as
a `Runner` for the evals. Needs NumPy (kit only).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from jarvis.localspeech.wakeword.formats import DIM, FEATURES, FRAMES
from jarvis.localspeech.wakeword.onnx_write import Dense

F32 = NDArray[np.float32]


@dataclass(frozen=True)
class Recipe:
    """How much work one stage 2 run does (the kit's defaults; tests pass a small one)."""

    hidden: int = 64
    layers: int = 2
    epochs: int = 30
    batch: int = 512
    lr: float = 1e-3
    weight_decay: float = 1e-4
    negative_weight: float = 2.0  # after balancing the classes
    copies: int = 8  # noisy copies of each of his clips
    tv_train_s: float = 3_600.0  # synthetic TV to learn from
    tv_eval_s: float = 7_200.0  # WAKE_BARS.tv_audio_hours
    seed: int = 0


@dataclass
class Mlp:
    weights: list[F32]  # [in, out] each
    biases: list[F32]
    mean: F32
    scale: F32

    @classmethod
    def start(cls, x: F32, recipe: Recipe, rng: np.random.Generator) -> Mlp:
        sizes = [FEATURES] + [recipe.hidden] * recipe.layers + [1]
        weights = [
            (rng.standard_normal((a, b)) * np.sqrt(2.0 / a)).astype(np.float32)
            for a, b in zip(sizes, sizes[1:], strict=False)
        ]
        biases = [np.zeros(b, dtype=np.float32) for b in sizes[1:]]
        scale = x.std(axis=0)
        return cls(
            weights, biases, x.mean(axis=0), np.where(scale > 0, scale, 1).astype(np.float32)
        )

    def _forward(self, x: F32) -> list[F32]:
        acts = [((x - self.mean) / self.scale).astype(np.float32)]
        for i, (w, b) in enumerate(zip(self.weights, self.biases, strict=True)):
            z = acts[-1] @ w + b
            last = i == len(self.weights) - 1
            acts.append((1 / (1 + np.exp(-z))).astype(np.float32) if last else np.maximum(z, 0))
        return acts

    def predict(self, x: F32) -> F32:
        return self._forward(x)[-1][:, 0]

    def _step(self, x: F32, y: F32, wt: F32, recipe: Recipe, adam: _Adam) -> None:
        acts = self._forward(x)
        delta = ((acts[-1][:, 0] - y) * wt / wt.sum())[:, None].astype(np.float32)
        grads: list[tuple[F32, F32]] = []
        for i in range(len(self.weights) - 1, -1, -1):
            gw = acts[i].T @ delta + recipe.weight_decay * self.weights[i]
            grads.append((gw.astype(np.float32), delta.sum(axis=0)))
            if i:
                delta = (delta @ self.weights[i].T) * (acts[i] > 0)
        adam.apply(self, grads[::-1])

    @classmethod
    def fit(
        cls, x: F32, y: F32, recipe: Recipe, progress: Callable[[float], None] | None = None
    ) -> Mlp:
        rng = np.random.default_rng(recipe.seed)
        mlp = cls.start(x, recipe, rng)
        pos = float(y.sum())
        neg = float(y.shape[0] - pos)
        if pos == 0 or neg == 0:
            raise ValueError("training needs both kinds of example")
        wt = np.where(y > 0, neg / pos, recipe.negative_weight).astype(np.float32)
        adam = _Adam.like(mlp, recipe.lr)
        for epoch in range(recipe.epochs):
            order = rng.permutation(x.shape[0])
            for at in range(0, order.shape[0], recipe.batch):
                idx = order[at : at + recipe.batch]
                mlp._step(x[idx], y[idx], wt[idx], recipe, adam)
            if progress is not None:
                progress((epoch + 1) / recipe.epochs)
        return mlp

    def dense(self) -> list[Dense]:
        """The layers with the standardisation folded in, [out][in] row-major."""
        w0: F32 = (self.weights[0] / self.scale[:, None]).astype(np.float32)
        b0: F32 = (self.biases[0] - (self.mean / self.scale) @ self.weights[0]).astype(np.float32)
        ws: list[F32] = [w0, *self.weights[1:]]
        bs: list[F32] = [b0, *self.biases[1:]]
        last = len(ws) - 1
        return [
            Dense(
                weight=w.T.astype(np.float32).reshape(-1).tolist(),
                bias=b.astype(np.float32).tolist(),
                n_in=w.shape[0],
                n_out=w.shape[1],
                activation="sigmoid" if i == last else "relu",
            )
            for i, (w, b) in enumerate(zip(ws, bs, strict=True))
        ]

    def runner(self) -> Callable[[F32], F32]:
        def run(x: F32) -> F32:
            flat = np.asarray(x, dtype=np.float32).reshape(-1, FRAMES * DIM)
            return self.predict(flat).reshape(-1, 1)

        return run


@dataclass
class _Adam:
    lr: float
    m: list[tuple[F32, F32]]
    v: list[tuple[F32, F32]]
    t: int = 0
    b1: float = 0.9
    b2: float = 0.999
    eps: float = 1e-8

    @classmethod
    def like(cls, mlp: Mlp, lr: float) -> _Adam:
        zeros = [
            (np.zeros_like(w), np.zeros_like(b))
            for w, b in zip(mlp.weights, mlp.biases, strict=True)
        ]
        return cls(lr=lr, m=list(zeros), v=[(z.copy(), c.copy()) for z, c in zeros])

    def apply(self, mlp: Mlp, grads: list[tuple[F32, F32]]) -> None:
        self.t += 1
        fix1, fix2 = 1 - self.b1**self.t, 1 - self.b2**self.t
        for i, (gw, gb) in enumerate(grads):
            (mw, mb), (vw, vb) = self.m[i], self.v[i]
            mw, mb = self.b1 * mw + (1 - self.b1) * gw, self.b1 * mb + (1 - self.b1) * gb
            vw, vb = self.b2 * vw + (1 - self.b2) * gw**2, self.b2 * vb + (1 - self.b2) * gb**2
            self.m[i], self.v[i] = (mw, mb), (vw, vb)
            mlp.weights[i] = (
                mlp.weights[i] - self.lr * (mw / fix1) / (np.sqrt(vw / fix2) + self.eps)
            ).astype(np.float32)
            mlp.biases[i] = (
                mlp.biases[i] - self.lr * (mb / fix1) / (np.sqrt(vb / fix2) + self.eps)
            ).astype(np.float32)


__all__ = ["Mlp", "Recipe"]
