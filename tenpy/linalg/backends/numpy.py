# Copyright 2023-2023 TeNPy Developers, GNU GPLv3
from __future__ import annotations

from typing import Any, TYPE_CHECKING
import numpy as np
import scipy

from .abelian import AbstractAbelianBackend
from .abstract_backend import AbstractBlockBackend, Block, Data, Dtype
from .no_symmetry import AbstractNoSymmetryBackend
from .nonabelian import AbstractNonabelianBackend
from ..misc import inverse_permutation
from ..symmetries.spaces import VectorSpace

__all__ = ['NumpyBlockBackend', 'NoSymmetryNumpyBackend', 'AbelianNumpyBackend', 'NonabelianNumpyBackend']


if TYPE_CHECKING:
    # can not import Tensor at runtime, since it would be a circular import
    # this clause allows mypy etc to evaluate the type-hints anyway
    from ..tensors import Tensor


class NumpyBlockBackend(AbstractBlockBackend):
    BlockCls = np.ndarray
    svd_algorithms = ['gesdd', 'gesvd', 'robust', 'robust_silent']

    tenpy_dtype_map = {
        np.float32: Dtype.float32,
        np.float64: Dtype.float64,
        np.complex64: Dtype.complex64,
        np.complex128: Dtype.complex128,
        np.dtype('float32'): Dtype.float32,
        np.dtype('float64'): Dtype.float64,
        np.dtype('complex64'): Dtype.complex64,
        np.dtype('complex128'): Dtype.complex128,
    }
    backend_dtype_map = {
        Dtype.float32: np.float32,
        Dtype.float64: np.float64,
        Dtype.complex64: np.complex64,
        Dtype.complex128: np.complex128,
    }

    def block_tdot(self, a: Block, b: Block, idcs_a: list[int], idcs_b: list[int]) -> Block:
        return np.tensordot(a, b, (idcs_a, idcs_b))

    def block_shape(self, a: Block) -> tuple[int]:
        return np.shape(a)

    def block_item(self, a: Block) -> float | complex:
        return a.item()

    def block_dtype(self, a: Block) -> Dtype:
        return self.tenpy_dtype_map[a.dtype]

    def block_to_dtype(self, a: Block, dtype: Dtype) -> Block:
        return np.asarray(a, dtype=self.backend_dtype_map[dtype])

    def block_copy(self, a: Block) -> Block:
        return np.copy(a)

    def _block_repr_lines(self, a: Block, indent: str, max_width: int, max_lines: int) -> list[str]:
        # TODO i like julia style much better actually, especially for many legs
        with np.printoptions(linewidth=max_width - len(indent)):
            lines = [f'{indent}{line}' for line in str(a).split('\n')]
        if len(lines) > max_lines:
            first = (max_lines - 1) // 2
            last = max_lines - 1 - first
            lines = lines[:first] + [f'{indent}...'] + lines[-last:]
        return lines

    def block_outer(self, a: Block, b: Block) -> Block:
        return np.tensordot(a, b, ((), ()))

    def block_inner(self, a: Block, b: Block, axs2: list[int] | None) -> complex:
        dim = max(a.ndim, b.ndim)
        axs2 = list(range(dim)) if axs2 is None else axs2
        return np.tensordot(np.conj(a), b, (list(range(dim)), axs2)).item()

    def block_transpose(self, a: Block, permutation: list[int]) -> Block:
        return np.transpose(a, permutation)

    def block_trace_full(self, a: Block, idcs1: list[int], idcs2: list[int]) -> float | complex:
        a = np.transpose(a, idcs1 + idcs2)
        trace_dim = np.prod(a.shape[:len(idcs1)])
        a = np.reshape(a, (trace_dim, trace_dim))
        return np.trace(a, axis1=0, axis2=1)

    def block_trace_partial(self, a: Block, idcs1: list[int], idcs2: list[int], remaining: list[int]) -> Block:
        a = np.transpose(a, remaining + idcs1 + idcs2)
        trace_dim = np.prod(a.shape[len(remaining):len(remaining)+len(idcs1)])
        a = np.reshape(a, a.shape[:len(remaining)] + (trace_dim, trace_dim))
        return np.trace(a, axis1=-2, axis2=-1)

    def block_conj(self, a: Block) -> Block:
        return np.conj(a)

    def block_allclose(self, a: Block, b: Block, rtol: float, atol: float) -> bool:
        return np.allclose(a, b, rtol=rtol, atol=atol)

    def block_squeeze_legs(self, a: Block, idcs: list[int]) -> Block:
        return np.squeeze(a, tuple(idcs))

    def block_norm(self, a: Block) -> float:
        return np.linalg.norm(a)

    def block_max_abs(self, a: Block) -> float:
        return np.max(np.abs(a))

    def block_reshape(self, a: Block, shape: tuple[int]) -> Block:
        return np.reshape(a, shape)

    def block_matrixify(self, a: Block, idcs1: list[int], idcs2: list[int]) -> tuple[Block, Any]:
        permutation = idcs1 + idcs2
        a = np.transpose(a, permutation)
        a_shape = np.shape(a)
        matrix_shape = np.prod(a_shape[:len(idcs1)]), np.prod(a_shape[len(idcs1):])
        matrix = np.reshape(a, matrix_shape)
        aux = (permutation, a_shape)
        return matrix, aux

    def block_dematrixify(self, matrix: Block, aux: Any) -> Block:
        permutation, a_shape = aux
        res = np.reshape(matrix, a_shape)
        return np.transpose(res, inverse_permutation(permutation))

    def matrix_dot(self, a: Block, b: Block) -> Block:
        return np.dot(a, b)

    # noinspection PyTypeChecker
    def matrix_svd(self, a: Block, algorithm: str | None) -> tuple[Block, Block, Block]:
        if algorithm is None:
            algorithm = 'gesdd'

        if algorithm == 'gesdd':
            return scipy.linalg.svd(a, full_matrices=False)

        elif algorithm in ['robust', 'robust_silent']:
            silent = algorithm == 'robust_silent'
            try:
                return scipy.linalg.svd(a, full_matrices=False)
            except np.linalg.LinAlgError:
                if not silent:
                    raise NotImplementedError  # TODO log warning
            return _svd_gesvd(a)

        elif algorithm == 'gesvd':
            return _svd_gesvd(a)

        else:
            raise ValueError(f'SVD algorithm not supported: {algorithm}')

    def matrix_qr(self, a: Block, full: bool) -> tuple[Block, Block]:
        return scipy.linalg.qr(a, mode='full' if full else 'economic')

    def matrix_exp(self, matrix: Block) -> Block:
        return scipy.linalg.expm(matrix)

    def matrix_log(self, matrix: Block) -> Block:
        return scipy.linalg.logm(matrix)

    def block_random_uniform(self, dims: list[int], dtype: Dtype) -> Block:
        res = np.random.uniform(-1, 1, size=dims)
        if not dtype.is_real:
            res += 1.j * np.random.uniform(-1, 1, size=dims)
        return res

    def block_random_normal(self, dims: list[int], dtype: Dtype, sigma: float) -> Block:
        res = np.random.normal(loc=0, scale=sigma, size=dims)
        if not dtype.is_real:
            res += 1.j * np.random.normal(loc=0, scale=sigma, size=dims)
        return res

    def block_from_numpy(self, a: np.ndarray) -> Block:
        return a

    def zero_block(self, shape: list[int], dtype: Dtype) -> Block:
        return np.zeros(shape, dtype=self.backend_dtype_map[dtype])

    def eye_block(self, legs: list[int], dtype: Dtype) -> Data:
        matrix_dim = np.prod(legs)
        eye = np.eye(matrix_dim, dtype=self.backend_dtype_map[dtype])
        eye = np.reshape(eye, legs + legs)
        return eye


class NoSymmetryNumpyBackend(NumpyBlockBackend, AbstractNoSymmetryBackend):
    pass


class AbelianNumpyBackend(NumpyBlockBackend, AbstractAbelianBackend):
    pass


class NonabelianNumpyBackend(NumpyBlockBackend, AbstractNonabelianBackend):
    pass


def _svd_gesvd(a):
    raise NotImplementedError  # TODO
