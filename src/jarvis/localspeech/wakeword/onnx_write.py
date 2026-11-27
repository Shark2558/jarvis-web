# src/jarvis/localspeech/wakeword/onnx_write.py
"""Writes stage 2's owned model as ONNX in the console's format (R5.2 row 83), with no ONNX
package: the few protobuf fields a small dense network needs, written by hand (onnx.proto,
Apache-2.0, field numbers as published). Pure Python (`struct`), kit-safe.

The graph is the shape of today's `hey_jarvis_v0.1.onnx` (IR 7, opset 13, as PyTorch writes it):

    features [1, 16, 96] float32 -> Flatten(axis=1) -> Gemm(transB=1) -> Relu -> ... -> Gemm
                                 -> Sigmoid -> score [1, 1] float32

so `console-wakeword.js` runs it unchanged (`inputNames[0]`, `outputNames[0]`). Each `Dense`
holds PyTorch's layout: `weight` is [out][in], row-major.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from jarvis.localspeech.wakeword.formats import DIM, FRAMES

IR_VERSION: Final = 7
OPSET: Final = 13
FLOAT: Final = 1  # TensorProto.FLOAT
ATTR_INT: Final = 2  # AttributeProto.INT
INPUT: Final = "features"
OUTPUT: Final = "score"
Activation = Literal["relu", "sigmoid"]


@dataclass(frozen=True)
class Dense:
    weight: Sequence[float]  # [n_out][n_in], row-major
    bias: Sequence[float]  # [n_out]
    n_in: int
    n_out: int
    activation: Activation

    def __post_init__(self) -> None:
        if len(self.weight) != self.n_in * self.n_out or len(self.bias) != self.n_out:
            raise ValueError("a layer's weights do not match its shape")
        if not all(math.isfinite(v) for v in (*self.weight, *self.bias)):
            raise ValueError("a layer's weights must be finite")


# ---- protobuf, by hand ---------------------------------------------------------------------------
def _varint(value: int) -> bytes:
    if value < 0:
        value += 1 << 64  # int64 as two's complement, as protobuf does
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _key(field: int, wire: int) -> bytes:
    return _varint(field << 3 | wire)


def _int(field: int, value: int) -> bytes:
    return _key(field, 0) + _varint(value)


def _bytes(field: int, value: bytes) -> bytes:
    return _key(field, 2) + _varint(len(value)) + value


def _str(field: int, value: str) -> bytes:
    return _bytes(field, value.encode("utf-8"))


def _tensor(name: str, dims: Sequence[int], values: Sequence[float]) -> bytes:
    raw = struct.pack(f"<{len(values)}f", *values)
    return b"".join(_int(1, d) for d in dims) + _int(2, FLOAT) + _str(8, name) + _bytes(9, raw)


def _value_info(name: str, dims: Sequence[int]) -> bytes:
    shape = b"".join(_bytes(1, _int(1, d)) for d in dims)  # Dimension.dim_value
    tensor_type = _int(1, FLOAT) + _bytes(2, shape)
    return _str(1, name) + _bytes(2, _bytes(1, tensor_type))


def _attr_int(name: str, value: int) -> bytes:
    return _str(1, name) + _int(3, value) + _int(20, ATTR_INT)


def _node(
    op: str, inputs: Sequence[str], outputs: Sequence[str], name: str, *attrs: bytes
) -> bytes:
    body = b"".join(_str(1, i) for i in inputs) + b"".join(_str(2, o) for o in outputs)
    return body + _str(3, name) + _str(4, op) + b"".join(_bytes(5, a) for a in attrs)


def _layers(layers: Sequence[Dense]) -> tuple[list[bytes], list[bytes]]:
    nodes = [_node("Flatten", [INPUT], ["x0"], "flatten", _attr_int("axis", 1))]
    inits: list[bytes] = []
    current = "x0"
    for i, layer in enumerate(layers, start=1):
        w, b, z, a = f"dense{i}.weight", f"dense{i}.bias", f"z{i}", f"a{i}"
        inits.append(_tensor(w, (layer.n_out, layer.n_in), layer.weight))
        inits.append(_tensor(b, (layer.n_out,), layer.bias))
        nodes.append(_node("Gemm", [current, w, b], [z], f"gemm{i}", _attr_int("transB", 1)))
        out = OUTPUT if i == len(layers) else a
        op = "Relu" if layer.activation == "relu" else "Sigmoid"
        nodes.append(_node(op, [z], [out], f"{op.lower()}{i}"))
        current = out
    return nodes, inits


def mlp_onnx(layers: Sequence[Dense], *, metadata: dict[str, str] | None = None) -> bytes:
    """The owned model's bytes. `layers` start at FRAMES * DIM inputs and end in one sigmoid."""
    if not layers or layers[0].n_in != FRAMES * DIM or layers[-1].n_out != 1:
        raise ValueError("the model reads 16 x 96 features and gives one score")
    if layers[-1].activation != "sigmoid" or any(x.activation != "relu" for x in layers[:-1]):
        raise ValueError("hidden layers are ReLU and the last one a sigmoid")
    for before, after in zip(layers, layers[1:], strict=False):
        if before.n_out != after.n_in:
            raise ValueError("the layers do not fit together")
    nodes, inits = _layers(layers)
    graph = (
        b"".join(_bytes(1, n) for n in nodes)
        + _str(2, "hey_jarvis_owned")
        + b"".join(_bytes(5, t) for t in inits)
        + _bytes(11, _value_info(INPUT, (1, FRAMES, DIM)))
        + _bytes(12, _value_info(OUTPUT, (1, 1)))
    )
    props = b"".join(
        _bytes(14, _str(1, k) + _str(2, v)) for k, v in sorted((metadata or {}).items())
    )
    return (
        _int(1, IR_VERSION)
        + _str(2, "jarvis-localspeech-wakeword")
        + _str(3, "1")
        + _bytes(7, graph)
        + _bytes(8, _int(2, OPSET))  # the default domain
        + props
    )


__all__ = ["INPUT", "IR_VERSION", "OPSET", "OUTPUT", "Dense", "mlp_onnx"]
