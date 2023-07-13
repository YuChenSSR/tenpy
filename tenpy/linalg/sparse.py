"""Providing support for sparse algorithms (using matrix-vector products only).

Some linear algebra algorithms, e.g. Lanczos, do not require the full representations of a linear
operator, but only the action on a vector, i.e., a matrix-vector product `matvec`. Here we define
the strucuture of such a general operator, :class:`NpcLinearOperator`, as it is used in our own
implementations of these algorithms (e.g., :mod:`~tenpy.linalg.lanczos`). Moreover, the
:class:`FlatLinearOperator` allows to use all the scipy sparse methods by providing functionality
to convert flat numpy arrays to and from np_conserved arrays.

TODO revise docstring
"""
# Copyright 2018-2021 TeNPy Developers, GNU GPLv3

from __future__ import annotations
from abc import ABC, abstractmethod
from numbers import Number
import warnings
import numpy as np

from .tensors import AbstractTensor, Shape, Tensor
from .backends.abstract_backend import Dtype


__all__ = ['TenpyLinearOperator', 'TenpyLinearOperatorWrapper', 'SumTenpyLinearOperator',
           'ShiftedTenpyLinearOperator', 'ProjectedTenpyLinearOperator']


class TenpyLinearOperator(ABC):
    """Base class for a linear operator acting on tenpy tensors.

    Attributes
    ----------
    vector_shape : Shape
        The shape of tensors that this operator can act on
    dtype : Dtype
        The dtype of a full representation of the operator
    """
    def __init__(self, vector_shape: Shape, dtype: Dtype):
        self.vector_shape = vector_shape
        self.dtype = dtype

    @abstractmethod
    def matvec(self, vec: AbstractTensor) -> AbstractTensor:
        """Apply the linear operator to a "vector".

        We consider as vectors all tensors of the shape given by :attr:`vector_shape`,
        and in particular allow multi-leg tensors as "vectors".
        The result of `matvec` must be a tensor of the same shape.
        """
        ...

    @abstractmethod
    def to_matrix(self):
        # TODO
        #   - should the result be a "matrix", i.e. forced to have two legs?
        #     if not, rename the method?
        #   - implement in derived classes
        #   - add tests
        raise NotImplementedError

    def adjoint(self) -> TenpyLinearOperator:
        """Return the hermitian conjugate operator.

        If `self` is hermitian, subclasses *can* choose to implement this to define
        the adjoint operator of `self` to be `self`.
        """
        raise NotImplementedError("No adjoint defined")


class TensorLinearOperator(TenpyLinearOperator):
    """Linear operator defined by a two-leg tensor with contractible legs.

    The matvec is defined by contracting one of the two legs of this tensor with the vector.
    This class is effectively a thin wrapper around tensors that allows them to be used as inputs
    for sparse linear algebra routines, such as lanczos.

    Parameter
    ---------
    tensor :
        The tensor that is contracted with the vector on matvec
    which_legs : int or str
        Which leg of `tensor` is to be contracted on matvec.
    """
    def __init__(self, tensor: Tensor, which_leg: int | str = -1):
        if tensor.num_legs > 2:
            raise ValueError('Expected a two-leg tensor')
        if not tensor.legs[0].can_contract_with(tensor.legs[1]):
            raise ValueError('Expected contractible legs')
        self.which_leg = which_leg = tensor.get_leg_idx(which_leg)
        self.other_leg = other_leg = 1 - which_leg
        self.tensor = tensor
        vector_shape = Shape(legs=[tensor.legs[other_leg]], labels=tensor.labels[other_leg])
        super().__init__(vector_shape=vector_shape, dtype=tensor.dtype)

    def matvec(self, vec: AbstractTensor) -> AbstractTensor:
        assert vec.num_legs == 1
        return self.tensor.tdot(vec, self.which_leg, 0)

    def adjoint(self) -> TensorLinearOperator:
        return TensorLinearOperator(tensor=self.tensor.conj(), which_leg=self.other_leg)


class TenpyLinearOperatorWrapper(TenpyLinearOperator, ABC):
    """Base class for wrapping around another :class:`TenpyLinearOperator`.

    Attributes which are not explicitly set, e.g. via `self.attribute = value` or by
    defining methods default to the attributes of the `original_operator`.

    This behavior is particularly useful when wrapping some concrete subclass of TenpyLinearOperator,
    which defines additional attributes.
    Using this base class, we can define the wrappers below without considering those extra attributes.

    .. warning ::
        If there are multiple levels of wrapping operators, the order might be critical to get
        correct results; e.g. :class:`OrthogonalTenpyLinearOperator` needs to be the outer-most
        wrapper to produce correct results and/or be efficient.

    Parameters
    ----------
    original_operator : :class:`TenpyLinearOperator`
        The original operator implementing the `matvec`.
    """
    def __init__(self, original_operator: TenpyLinearOperator):
        self.original_operator = original_operator
        # TODO (JU) should we call TenpyLinearOperator.__init__ or super().__init__ here?
        #      Its current implementation only sets attributes, which we dont need because
        #      we hack into __getattr__

    def __getattr__(self, name):
        # note: __getattr__ (unlike __getattribute__) is only called if the attribute is not
        #       found in the __dict__, so it is the fallback for attributes that are not explicitly set.
        return getattr(self.original_operator, name)

    def unwrapped(self, recursive: bool = True) -> TenpyLinearOperator:
        """Return the original `TenpyLinearOperator`

        By default, unwrapping is done recursively, such that the result is *not* a `TenpyLinearOperatorWrapper`.
        """
        parent = self.original_operator
        if not recursive:
            return parent
        for _ in range(10000):
            try:
                parent = parent.unwrapped()
            except AttributeError:
                # parent has no :meth:`unwrapped`, so we can stop unwrapping
                return parent
        raise ValueError('maximum recursion depth for unwrapping reached')


class SumTenpyLinearOperator(TenpyLinearOperatorWrapper):
    """The sum of multiple operators"""
    def __init__(self, original_operator: TenpyLinearOperator, *more_operators: TenpyLinearOperator):
        super().__init__(original_operator=original_operator)
        assert all(op.vector_shape == original_operator.vector_shape for op in more_operators)
        self.more_operators = more_operators
        self.dtype = Dtype.common(original_operator.dtype, *(op.dtype for op in more_operators))

    def matvec(self, vec: AbstractTensor) -> AbstractTensor:
        return sum((op.matvec(vec) for op in self.more_operators), self.original_operator.matvec(vec))

    def adjoint(self) -> TenpyLinearOperator:
        return SumTenpyLinearOperator(self.original_operator.adjoint(),
                                      *(op.adjoint() for op in self.more_operators))


class ShiftedTenpyLinearOperator(TenpyLinearOperatorWrapper):
    """A shifted operator, i.e. ``original_operator + shift * identity``.

    This can be useful e.g. for better Lanczos convergence.
    """
    def __init__(self, original_operator: TenpyLinearOperator, shift: Number):
        if shift in [0, 0.]:
            warnings.warn('shift=0: no need for ShiftedTenpyLinearOperator', stacklevel=2)
        super().__init__(original_operator=original_operator)
        self.shift = shift
        if np.iscomplexobj(shift):
            self.dtype = original_operator.dtype.to_complex

    def matvec(self, vec: AbstractTensor) -> AbstractTensor:
        return self.original_operator.matvec(vec) + self.shift * vec

    def adjoint(self):
        return ShiftedTenpyLinearOperator(original_operator=self.original_operator.adjoint(),
                                          shift=np.conj(self.shift))


class ProjectedTenpyLinearOperator(TenpyLinearOperatorWrapper):
    """Projected version ``P H P + penalty * (1 - P)`` of an original operator ``H``.

    The projector ``P = 1 - sum_o |o> <o|`` is given in terms of a set :attr:`ortho_vecs` of vectors
    ``|o>``.
    
    The result is that all vectors from the subspace spanned by the :attr:`ortho_vecs` are eigenvectors
    with eigenvalue `penalty`, while the eigensystem in the "rest" (i.e. in the orthogonal complement
    to that subspace) remains unchanged.
    This can be used to exclude the :attr:`ortho_vecs` from extremal eigensolvers.

    Parameters
    ----------
    original_operator : :class:`TenpyLinearOperator`
        The original operator, denoted ``H`` in the summary above.
    ortho_vecs : list of :class:`~tenpy.linalg.tensors.AbstractTensor`
        TODO (JU) different name?
        The list of vectors spanning the projected space.
        They need not be orthonormal, as Gram-Schmidt is performed on them explicitly.
    penalty : complex, optional
        See summary above. Defaults to ``None``, which is equivalent to ``0.``.
    """
    def __init__(self, original_operator: TenpyLinearOperator, ortho_vecs: list[AbstractTensor],
                 penalty: Number = None):
        if len(ortho_vecs) == 0:
            warnings.warn('empty ortho_vecs: no need for ProjectedTenpyLinearOperator', stacklevel=2)
        super().__init__(original_operator=original_operator)
        assert all(v.shape == original_operator.vector_shape for v in ortho_vecs)
        from .lanczos import gram_schmidt
        self.ortho_vecs = gram_schmidt(ortho_vecs)
        self.penalty = penalty

    def matvec(self, vec: AbstractTensor) -> AbstractTensor:
        res = vec
        # form ``P vec`` and keep coefficients for later use in the penalty term
        coefficients = []
        for o in self.ortho_vecs:
            c = o.inner(res)
            coefficients.append(c)
            res = res - c * o
        # ``H P vec``
        res = self.original_operator.matvec(res)
        # ``P H P vec``
        for o in reversed(self.ortho_vecs):
            # reverse: more obviously Hermitian.
            # TODO (JU) i dont see how the order makes a difference here or why reverse is better...
            #           @jhauschild, i just took this from the previous implementation.
            #           could you expand the explanation?
            res = res - o.inner(res) * o
        if self.penalty is not None:
            for c, o in zip(coefficients, self.ortho_vecs):
                res = res + self.penalty * c * o
        return res
        
    def adjoint(self) -> TenpyLinearOperator:
        return ProjectedTenpyLinearOperator(
            original_operator=self.original_operator.adjoint(),
            ortho_vecs=self.ortho_vecs,  # hc(|o> <o|) = |o> <o|  ->  can use same ortho_vecs
            penalty=None if self.penalty is None else np.conj(self.penalty)
        )


# TODO (JU) port FlatLinearOperator from old
