# Copyright 2023-2023 TeNPy Developers, GNU GPLv3
from __future__ import annotations

import logging

from .abstract_backend import AbstractBackend
from .numpy import NoSymmetryNumpyBackend, AbelianNumpyBackend
from .torch import NoSymmetryTorchBackend, AbelianTorchBackend
from ..groups import Symmetry, no_symmetry, AbelianGroup

__all__ = ['get_backend']

logger = logging.getLogger(__name__)


_backend_lookup = dict(
    no_symmetry=dict(
        numpy=(NoSymmetryNumpyBackend, {}),
        torch=(NoSymmetryTorchBackend, {}),
        tensorflow=None,  # TODO
        jax=None,  # TODO
        cpu=(NoSymmetryNumpyBackend, {}),
        gpu=(NoSymmetryTorchBackend, dict(device='cuda')),
        tpu=None,  # TODO
    ),
    #
    abelian=dict(
        numpy=(AbelianNumpyBackend, {}),
        torch=(AbelianTorchBackend, {}),
        tensorflow=None,  # FUTURE
        jax=None,  # FUTURE
        cpu=(AbelianNumpyBackend, {}),
        gpu=(AbelianTorchBackend, dict(device='cuda')),
        tpu=None,  # FUTURE
    ),
    #
    non_abelian=dict(
        numpy=None,  # FUTURE
        torch=None,  # FUTURE
        tensorflow=None,  # FUTURE
        jax=None,  # FUTURE
        cpu=None,  # FUTURE
        gpu=None,  # FUTURE
        tpu=None,  # FUTURE
    ),
)

_instantiated_backends = {}  # keys: (symmetry_backend, block_backend, kwargs)


def get_backend(symmetry: Symmetry = no_symmetry, block_backend: str = 'numpy',
                symmetry_backend: str = None) -> AbstractBackend:
    """
    Parameters
    ----------
    symmetry : AbstractSymmetry
    block_backend : {'numpy', 'torch', 'tensorflow', 'jax', 'cpu', 'gpu', 'tpu'}
    symmetry_backend : {None, 'no_symmetry', 'abelian', 'nonabelian'}
        None means select based on the symmetry.
        It is possible though, to request the non-abelian backend even though the symmetry is
        actually abelian.
    """
    # TODO cache these instances, make sure there is only ever one.
    #  -> need hash for AbstractSymmetry instances
    assert block_backend in ['numpy', 'torch', 'tensorflow', 'jax', 'cpu', 'gpu', 'tpu']
    if symmetry_backend is None:
        if symmetry == no_symmetry:
            symmetry_backend = 'no_symmetry'
        # TODO (JU) should instancheck abelian group instead.
        #  abelian backend does not support general abelian fusion categories, e.g. fermion parity
        elif symmetry.is_abelian:
            symmetry_backend = 'abelian'
        else:
            symmetry_backend = 'nonabelian'
    assert symmetry_backend in ['no_symmetry', 'abelian', 'nonabelian']

    res = _backend_lookup[symmetry_backend][block_backend]
    if res is None:
        raise NotImplementedError(f'Backend not implemented {symmetry_backend} & {block_backend}')
    cls, kwargs = res

    key = (symmetry_backend, block_backend, tuple(kwargs.items()))
    if key not in _instantiated_backends:
        backend = cls(**kwargs)
        _instantiated_backends[key] = backend
    else:
        backend = _instantiated_backends[key]
    return backend


def get_default_backend(symmetry: Symmetry = None):
    """dummy implementation for a settable backend global through all of tenpy"""
    # TODO: proper implementation
    kwargs = {} if symmetry is None else dict(symmetry=symmetry)
    return get_backend(**kwargs)
