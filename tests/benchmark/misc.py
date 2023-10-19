"""Common utility functions for benchmarks"""
# Copyright 2023 TeNPy Developers, GNU GPLv3
import numpy as np
from tenpy.linalg import groups, spaces
from tenpy.linalg.backends.abstract_backend import AbstractBackend
from tenpy.linalg.backends.numpy import NumpyBlockBackend
from tenpy.linalg.backends.no_symmetry import AbstractNoSymmetryBackend
from tenpy.linalg.backends.abelian import AbstractAbelianBackend
from tenpy.linalg.tensors import Tensor


def random_symmetry_sectors(symmetry: groups.Symmetry, np_random: np.random.Generator, len_=None
                            ) -> groups.SectorArray:
    """random non-sorted, but unique symmetry sectors"""
    if len_ is None:
        len_ = np_random.integers(3,7)
    if isinstance(symmetry, groups.SU2Symmetry):
        return np.arange(0, 2*len_, 2, dtype=int)[:, np.newaxis]
    elif isinstance(symmetry, groups.U1Symmetry):
        vals = list(range(-len_, len_)) + [123]
        return np_random.choice(vals, replace=False, size=(len_, 1))
    elif symmetry.num_sectors < np.inf:
        if symmetry.num_sectors <= len_:
            return np_random.permutation(symmetry.all_sectors())
        which = np_random.choice(symmetry.num_sectors, replace=False, size=len_)
        return symmetry.all_sectors()[which, :]
    elif isinstance(symmetry, groups.ProductSymmetry):
        factor_len = max(3, len_ // len(symmetry.factors))
        factor_sectors = [random_symmetry_sectors(factor, np_random, factor_len)
                          for factor in symmetry.factors]
        combs = np.indices([len(s) for s in factor_sectors]).T.reshape((-1, len(factor_sectors)))
        if len(combs) > len_:
            which = np_random.choice(len(combs), replace=False, size=len_)
            combs = combs[which]
        res = np.hstack([fs[i] for fs, i in zip(factor_sectors, combs.T)])
        return res


def parse_symmetry(symmetry: list[str]) -> groups.Symmetry:
    """Translate --symmetry argparse argument"""
    symmetry = [getattr(groups, s) for s in symmetry]
    symmetry = [s() if isinstance(s, type) else s for s in symmetry]
    assert all(isinstance(s, groups.Symmetry) for s in symmetry)
    if len(symmetry) == 0:
        return groups.no_symmetry
    if len(symmetry) == 1:
        return symmetry[0]
    return groups.ProductSymmetry(symmetry)


symmetry_short_names = dict(
    u1_symmetry='U1',
    U1Symmetry='U1',
    su2_symmetry='SU2',
    SU2Symmetry='SU2',
    fermion_parity='fermion',
    FermionParity='fermion',
    z2_symmetry='Z2',
    z3_symmetry='Z3',
    z4_symmetry='Z4',
    z5_symmetry='Z5',
    z6_symmetry='Z6',
    z7_symmetry='Z7',
    z8_symmetry='Z8',
    z9_symmetry='Z9',
)


def parse_backend(backend: list[str]) -> tuple[str, str]:
    """Translate --backend argparse argument to symmetry_backend and block_backend"""
    # default first:
    VALID_SYMMETRY_BACKENDS = ['abelian', 'no_symmetry', 'nonabelian']
    VALID_BLOCK_BACKENDS = ['numpy', 'torch', 'gpu']
    
    if len(backend) == 1:
        if backend[0] in VALID_SYMMETRY_BACKENDS:
            return backend[0], VALID_BLOCK_BACKENDS[0]
        if backend[0] in VALID_BLOCK_BACKENDS:
            return VALID_SYMMETRY_BACKENDS[0], backend[0]
    if len(backend) == 2:
        if backend[0] in VALID_SYMMETRY_BACKENDS and backend[1] in VALID_BLOCK_BACKENDS:
            return backend[0], backend[1]
        if backend[0] in VALID_BLOCK_BACKENDS and backend[1] in VALID_SYMMETRY_BACKENDS:
            return backend[1], backend[0]
    raise ValueError(f'Invalid backend specification: {backend}')


def rand_distinct_int(a, b, n):
    """returns n distinct integers from a to b inclusive."""
    if n < 0:
        raise ValueError
    if n > b - a + 1:
        raise ValueError
    return np.sort((np.random.random_integers(a, b - n + 1, size=n))) + np.arange(n)


def rand_partitions(a, b, n):
    """return [a] + `cuts` + [b], where `cuts` are ``n-1`` (strictly ordered) values inbetween."""
    if b - a <= n:
        return np.array(range(a, b + 1))
    else:
        return np.concatenate(([a], rand_distinct_int(a + 1, b - 1, n - 1), [b]))


def get_random_multiplicities(dim: int, num_sectors: int):
    slices = rand_partitions(0, dim, num_sectors)
    assert len(slices) == num_sectors + 1
    return slices[1:] - slices[:-1]


def get_random_leg(symmetry: groups.Symmetry, dim: int, num_sectors: int):
    assert num_sectors <= dim
    multiplicities = get_random_multiplicities(dim=dim, num_sectors=num_sectors)
    assert len(multiplicities) == num_sectors
    sectors = random_symmetry_sectors(symmetry=symmetry, np_random=np.random, len_=num_sectors)
    assert len(sectors) == num_sectors
    return spaces.VectorSpace(symmetry=symmetry, sectors=sectors, multiplicities=multiplicities)


def get_compatible_leg(legs: list[spaces.VectorSpace]) -> spaces.VectorSpace:
    """return a leg such that a tensor with ``legs + [result]`` allows a non-zero # of blocks."""
    fully_compatible = spaces.ProductSpace(legs).dual
    num_sectors = legs[0].num_sectors
    dim = legs[0].dim

    from_compatible = np.random.randint(num_sectors // 2, num_sectors)
    which = np.random.choice(fully_compatible.num_sectors, size=from_compatible, replace=False)
    rest = np.asarray([i for i in range(fully_compatible.num_sectors) if i not in which])
    sectors = fully_compatible.sectors[which]

    from_rest_or_random = num_sectors - from_compatible
    random_sectors = random_symmetry_sectors(symmetry=fully_compatible.symmetry, np_random=np.random,
                                             len_=len(rest))
    rest_and_random = np.concatenate([fully_compatible.sectors[rest], random_sectors])
    rest_and_random = np.unique(rest_and_random, axis=0)
    is_duplicate = np.any(np.all(rest_and_random[:, None, :] == sectors[None, :, :], axis=2), axis=1)
    rest_and_random = rest_and_random[np.logical_not(is_duplicate)]
    which = np.random.choice(len(rest_and_random), size=from_rest_or_random, replace=False)
    sectors = np.concatenate([sectors, rest_and_random[which]])
    assert len(np.unique(sectors, axis=0)) == len(sectors)

    assert sectors.shape == (num_sectors, fully_compatible.symmetry.sector_ind_len)
    return spaces.VectorSpace(
        symmetry=fully_compatible.symmetry, sectors=sectors,
        multiplicities=get_random_multiplicities(dim=dim, num_sectors=num_sectors),
    )


def get_random_tensor(symmetry: groups.Symmetry, backend: AbstractBackend,
                      legs: list[spaces.VectorSpace | None], leg_dim: int, sectors_per_leg: int,
                      real: bool = False):
    assert sectors_per_leg <= leg_dim

    # determine legs
    legs = legs[:]
    missing_legs = [i for i, leg in enumerate(legs) if leg is None]
    while len(missing_legs) > 1:
        legs[missing_legs[0]] = get_random_leg(symmetry=symmetry, dim=leg_dim, num_sectors=sectors_per_leg)
        missing_legs = [i for i, leg in enumerate(legs) if leg is None]
    if len(missing_legs) > 0:
        which, = missing_legs
        legs[which] = get_compatible_leg(legs[:which] + legs[which + 1:])
    
    def random_block(size):
        res = np.random.normal(size=size)
        if real:
            res = res + 1.j * np.random.normal(size=size)
        return res

    return Tensor.from_numpy_func(func=random_block, legs=legs, backend=backend)


def get_qmod(sym):
    """Get the (v0.x convention) qmod from a v2.0 symmetry"""
    if isinstance(sym, groups.ProductSymmetry):
        qmod = []
        for s in sym.factors:
            qmod.extend(get_qmod(s))
        return qmod
    if isinstance(sym, groups.U1Symmetry):
        return [1]
    if isinstance(sym, groups.ZNSymmetry):
        return [sym.N]
    if isinstance(sym, groups.NoSymmetry):
        return []
    raise NotImplementedError


def convert_VectorSpace_to_LegCharge(leg: spaces.VectorSpace, old_tenpy, chinfo=None):
    """Convert a v2.0 VectorSpace to a v0.x LegCharge"""
    if chinfo is None:
        chinfo = old_tenpy.linalg.charges.ChargeInfo(get_qmod(leg.symmetry))
    slices = np.insert(np.cumsum(leg.multiplicities), 0, 0)
    assert slices.shape == (leg.num_sectors + 1,)
    charges = leg._non_dual_sectors
    assert charges.shape == (leg.num_sectors, leg.symmetry.sector_ind_len)
    qconj = -1 if leg.is_dual else +1
    if chinfo.qnumber == 0:
        charges = [[]]
    return old_tenpy.linalg.charges.LegCharge(chinfo, slices, charges, qconj)


def convert_Tensor_to_Array(a: Tensor, old_tenpy, chinfo=None):
    """Convert a v2.0 Tensor to a v0.x Array

    If given, use chinfo, otherwise generate it from `a.symmetry`.
    """
    if not isinstance(a.backend, NumpyBlockBackend):
        # would need to convert blocks to numpy
        raise NotImplementedError
    if isinstance(a.backend, AbstractNoSymmetryBackend):
        return old_tenpy.linalg.np_conserved.Array.from_ndarray_trivial(a.data)
    assert isinstance(a.backend, AbstractAbelianBackend)
    if chinfo is None:
        chinfo = old_tenpy.linalg.charges.ChargeInfo(get_qmod(a.symmetry))
    legs = [convert_VectorSpace_to_LegCharge(l, old_tenpy, chinfo) for l in a.legs]
    res = old_tenpy.linalg.np_conserved.Array(legs)
    res._data = a.data.blocks
    res._qdata = a.data.block_inds
    res._qdata_sorted = True
    res.test_sanity()
    return res