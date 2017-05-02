#! /usr/bin/env python
# ============================================================
# Copyright (c) 2012, Lawrence Livermore National Security, LLC.
# Produced at the Lawrence Livermore National Laboratory.
# Written by Joel Bernier <bernier2@llnl.gov> and others.
# LLNL-CODE-529294.
# All rights reserved.
#
# This file is part of HEXRD. For details on dowloading the source,
# see the file COPYING.
#
# Please also see the file LICENSE.
#
# This program is free software; you can redistribute it and/or modify it under the
# terms of the GNU Lesser General Public License (as published by the Free Software
# Foundation) version 2.1 dated February 1999.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the IMPLIED WARRANTY OF MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the terms and conditions of the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program (see file LICENSE); if not, write to
# the Free Software Foundation, Inc., 59 Temple Place, Suite 330,
# Boston, MA 02111-1307 USA or visit <http://www.gnu.org/licenses/>.
# ============================================================

import numpy as np

# try:
#     from scipy.optimize import basinhopping
# except:
#     from scipy.optimize import leastsq
from scipy import optimize
return_value_flag = None

from hexrd import matrixutil as mutil

from hexrd.xrd import transforms      as xf
from hexrd.xrd import transforms_CAPI as xfcapi
from hexrd.xrd import distortion      as dFuncs

epsf      = np.finfo(float).eps # ~2.2e-16
sqrt_epsf = np.sqrt(epsf)       # ~1.5e-8

# ######################################################################
# Module Data
d2r = np.pi/180.
r2d = 180./np.pi

bVec_ref    = xf.bVec_ref
eta_ref     = xf.eta_ref
vInv_ref    = np.r_[1., 1., 1., 0., 0., 0.]

# for distortion
dFunc_ref   = dFuncs.GE_41RT
dParams_ref = [0., 0., 0., 2., 2., 2]
dFlag_ref   = np.array([0, 0, 0, 0, 0, 0], dtype=bool)
dScl_ref    = np.array([1, 1, 1, 1, 1, 1], dtype=float)

# for sx detector cal
pFlag_ref = np.array(
    [
        0,
        1, 1, 1,
        1, 1, 1,
        0,
        0, 0, 0,
        0, 0, 0,
        0, 0, 0
    ], dtype=bool
)
pScl_ref = np.array(
    [
        0.1,
        0.1, 0.1, 0.1,
        1., 1., 100.,
        0.1,
        1., 1., 1.,
        1., 1., 1.,
        1., 1., 1.
    ]
)

# for grain parameters
gFlag_ref   = np.ones(12, dtype=bool)
gScl_ref    = np.ones(12, dtype=bool)

"""
######################################################################
##############            UTILITY FUNCTIONS             ##############
######################################################################
"""

def matchOmegas(xyo_det, hkls_idx, chi, rMat_c, bMat, wavelength,
                vInv=vInv_ref, beamVec=bVec_ref, etaVec=eta_ref,
                omePeriod=None):
    """
    For a given list of (x, y, ome) points, outputs the index into the results from
    oscillAnglesOfHKLs, including the calculated omega values.
    """
    # get omegas for rMat_s calculation
    if omePeriod is not None:
        meas_omes = xf.mapAngle(xyo_det[:, 2], omePeriod)
    else:
        meas_omes = xyo_det[:, 2]

    oangs0, oangs1 = xfcapi.oscillAnglesOfHKLs(hkls_idx.T, chi, rMat_c, bMat, wavelength,
                                               vInv=vInv,
                                               beamVec=beamVec,
                                               etaVec=etaVec)
    if np.any(np.isnan(oangs0)):
        nanIdx = np.where(np.isnan(oangs0[:, 0]))[0]
        errorString = "Infeasible parameters for hkls:\n"
        for i in range(len(nanIdx)):
            errorString += "%d  %d  %d\n" % tuple(hkls_idx[:, nanIdx[i]])
        raise RuntimeError, errorString
    else:
        # CAPI version gives vstacked angles... must be (2, nhkls)
        calc_omes = np.vstack([oangs0[:, 2], oangs1[:, 2]])
    if omePeriod is not None:
        calc_omes  = np.vstack([xf.mapAngle(oangs0[:, 2], omePeriod),
                                xf.mapAngle(oangs1[:, 2], omePeriod)])
    # do angular difference
    diff_omes  = xf.angularDifference(np.tile(meas_omes, (2, 1)), calc_omes)
    match_omes = np.argsort(diff_omes, axis=0) == 0
    calc_omes  = calc_omes.T.flatten()[match_omes.T.flatten()]

    return match_omes, calc_omes

def geomParamsToInput(wavelength,
                      tiltAngles, chi, expMap_c,
                      tVec_d, tVec_s, tVec_c,
                      dParams):
    """
    """
    p = np.zeros(17)

    p[0]  = wavelength
    p[1]  = tiltAngles[0]
    p[2]  = tiltAngles[1]
    p[3]  = tiltAngles[2]
    p[4]  = tVec_d[0]
    p[5]  = tVec_d[1]
    p[6]  = tVec_d[2]
    p[7]  = chi
    p[8]  = tVec_s[0]
    p[9]  = tVec_s[1]
    p[10] = tVec_s[2]
    p[11] = expMap_c[0]
    p[12] = expMap_c[1]
    p[13] = expMap_c[2]
    p[14] = tVec_c[0]
    p[15] = tVec_c[1]
    p[16] = tVec_c[2]

    return np.hstack([p, dParams])

def inputToGeomParams(p):
    """
    """
    retval = {}

    retval['wavelength'] = p[0]
    retval['tiltAngles'] = (p[1], p[2], p[3])
    retval['tVec_d']     = np.c_[p[4], p[5], p[6]].T
    retval['chi']        = p[7]
    retval['tVec_s']     = np.c_[p[8], p[9], p[10]].T
    retval['expMap_c']   = np.c_[p[11], p[12], p[13]].T
    retval['tVec_c']     = np.c_[p[14], p[15], p[16]].T
    retval['dParams']    = p[17:]

    return retval

"""
######################################################################
##############               CALIBRATION                ##############
######################################################################
"""

def calibrateDetectorFromSX(
    xyo_det, hkls_idx, bMat, wavelength,
    tiltAngles, chi, expMap_c,
    tVec_d, tVec_s, tVec_c,
    vInv=vInv_ref,
    beamVec=bVec_ref, etaVec=eta_ref,
    distortion=(dFunc_ref, dParams_ref, dFlag_ref, dScl_ref),
    pFlag=pFlag_ref, pScl=pScl_ref,
    omePeriod=None,
    factor=0.1,
    xtol=sqrt_epsf, ftol=sqrt_epsf,
    ):
    """
    """
    if omePeriod is not None:
        xyo_det[:, 2] = xf.mapAngle(xyo_det[:, 2], omePeriod)

    dFunc   = distortion[0]
    dParams = distortion[1]
    dFlag   = distortion[2]
    dScl    = distortion[3]

    # p = np.zeros(17)
    #
    # p[0]  = wavelength
    # p[1]  = tiltAngles[0]
    # p[2]  = tiltAngles[1]
    # p[3]  = tiltAngles[2]
    # p[4]  = tVec_d[0]
    # p[5]  = tVec_d[1]
    # p[6]  = tVec_d[2]
    # p[7]  = chi
    # p[8]  = tVec_s[0]
    # p[9]  = tVec_s[1]
    # p[10] = tVec_s[2]
    # p[11] = expMap_c[0]
    # p[12] = expMap_c[1]
    # p[13] = expMap_c[2]
    # p[14] = tVec_c[0]
    # p[15] = tVec_c[1]
    # p[16] = tVec_c[2]
    #
    # pFull = np.hstack([p, dParams])

    pFull = geomParamsToInput(
        wavelength,
        tiltAngles, chi, expMap_c,
        tVec_d, tVec_s, tVec_c,
        dParams
        )

    refineFlag = np.hstack([pFlag, dFlag])
    scl        = np.hstack([pScl, dScl])
    pFit       = pFull[refineFlag]
    fitArgs    = (pFull, pFlag, dFunc, dFlag, xyo_det, hkls_idx,
                  bMat, vInv, beamVec, etaVec, omePeriod)

    results = optimize.leastsq(objFuncSX, pFit, args=fitArgs,
                               diag=1./scl[refineFlag].flatten(),
                               factor=factor, xtol=xtol, ftol=ftol)

    pFit_opt = results[0]

    retval = pFull
    retval[refineFlag] = pFit_opt
    return retval

def objFuncSX(pFit, pFull, pFlag, dFunc, dFlag,
              xyo_det, hkls_idx, bMat, vInv,
              bVec, eVec, omePeriod,
              simOnly=False, return_value_flag=return_value_flag):
    """
    """
    npts   = len(xyo_det)

    refineFlag = np.hstack([pFlag, dFlag])

    # pFull[refineFlag] = pFit/scl[refineFlag]
    pFull[refineFlag] = pFit

    dParams = pFull[-len(dFlag):]
    xy_unwarped = dFunc(xyo_det[:, :2], dParams)

    # detector quantities
    wavelength = pFull[0]

    rMat_d = xf.makeDetectorRotMat(pFull[1:4])
    tVec_d = pFull[4:7].reshape(3, 1)

    # sample quantities
    chi    = pFull[7]
    tVec_s = pFull[8:11].reshape(3, 1)

    # crystal quantities
    rMat_c = xf.makeRotMatOfExpMap(pFull[11:14])
    tVec_c = pFull[14:17].reshape(3, 1)

    gVec_c = np.dot(bMat, hkls_idx)
    vMat_s = mutil.vecMVToSymm(vInv)                # stretch tensor comp matrix from MV notation in SAMPLE frame
    gVec_s = np.dot(vMat_s, np.dot(rMat_c, gVec_c)) # reciprocal lattice vectors in SAMPLE frame
    gHat_s = mutil.unitVector(gVec_s)               # unit reciprocal lattice vectors in SAMPLE frame
    gHat_c = np.dot(rMat_c.T, gHat_s)               # unit reciprocal lattice vectors in CRYSTAL frame

    match_omes, calc_omes = matchOmegas(xyo_det, hkls_idx, chi, rMat_c, bMat, wavelength,
                                        vInv=vInv, beamVec=bVec, etaVec=eVec, omePeriod=omePeriod)

    calc_xy = np.zeros((npts, 2))
    for i in range(npts):
        rMat_s = xfcapi.makeOscillRotMat([chi, calc_omes[i]])
        calc_xy[i, :] = xfcapi.gvecToDetectorXY(gHat_c[:, i],
                                                rMat_d, rMat_s, rMat_c,
                                                tVec_d, tVec_s, tVec_c,
                                                beamVec=bVec).flatten()
        pass
    if np.any(np.isnan(calc_xy)):
        print "infeasible pFull: may want to scale back finite difference step size"

    # return values
    if simOnly:
        retval = np.hstack([calc_xy, calc_omes.reshape(npts, 1)])
    else:
        diff_vecs_xy = calc_xy - xy_unwarped[:, :2]
        diff_ome     = xf.angularDifference( calc_omes, xyo_det[:, 2] )
        retval = np.hstack([diff_vecs_xy,
                            diff_ome.reshape(npts, 1)
                            ]).flatten()
        if return_value_flag == 1:
            retval = sum( abs(retval) )
        elif return_value_flag == 2:
            denom = 3*npts - len(pFit) - 1.
            if denom != 0:
                nu_fac = 1. / denom
            else:
                nu_fac = 1.
            nu_fac = 1 / (npts - len(pFit) - 1.)
            retval = nu_fac * sum(retval**2)
    return retval

"""
######################################################################
##############              GRAIN FITTING               ##############
######################################################################
"""

def fitGrain(xyo_det, hkls_idx, bMat, wavelength,
             detectorParams,
             expMap_c, tVec_c, vInv,
             beamVec=bVec_ref, etaVec=eta_ref,
             distortion=(dFunc_ref, dParams_ref),
             gFlag=gFlag_ref, gScl=gScl_ref,
             omePeriod=None,
             factor=0.1, xtol=sqrt_epsf, ftol=sqrt_epsf):
    """
    """
    if omePeriod is not None:
        xyo_det[:, 2] = xf.mapAngle(xyo_det[:, 2], omePeriod)

    dFunc   = distortion[0]
    dParams = distortion[1]

    gFull = np.hstack([expMap_c.flatten(),
                       tVec_c.flatten(),
                       vInv.flatten()])

    gFit  = gFull[gFlag]

    fitArgs = (gFull, gFlag,
               detectorParams,
               xyo_det, hkls_idx, bMat, wavelength,
               beamVec, etaVec,
               dFunc, dParams,
               omePeriod)

    results = optimize.leastsq(objFuncFitGrain, gFit, args=fitArgs,
                               diag=1./gScl[gFlag].flatten(),
                               factor=0.1, xtol=xtol, ftol=ftol)

    gFit_opt = results[0]

    retval = gFull
    retval[gFlag] = gFit_opt
    return retval

def objFuncFitGrain(gFit, gFull, gFlag,
                    detectorParams,
                    xyo_det, hkls_idx, bMat, wavelength,
                    bVec, eVec,
                    dFunc, dParams,
                    omePeriod,
                    simOnly=False, return_value_flag=return_value_flag):
    """
    gFull[0]  = expMap_c[0]
    gFull[1]  = expMap_c[1]
    gFull[2]  = expMap_c[2]
    gFull[3]  = tVec_c[0]
    gFull[4]  = tVec_c[1]
    gFull[5]  = tVec_c[2]
    gFull[6]  = vInv_MV[0]
    gFull[7]  = vInv_MV[1]
    gFull[8]  = vInv_MV[2]
    gFull[9]  = vInv_MV[3]
    gFull[10] = vInv_MV[4]
    gFull[11] = vInv_MV[5]

    detectorParams[0]  = tiltAngles[0]
    detectorParams[1]  = tiltAngles[1]
    detectorParams[2]  = tiltAngles[2]
    detectorParams[3]  = tVec_d[0]
    detectorParams[4]  = tVec_d[1]
    detectorParams[5]  = tVec_d[2]
    detectorParams[6]  = chi
    detectorParams[7]  = tVec_s[0]
    detectorParams[8]  = tVec_s[1]
    detectorParams[9]  = tVec_s[2]
    """
    npts   = len(xyo_det)

    gFull[gFlag] = gFit

    xy_unwarped = dFunc(xyo_det[:, :2], dParams)

    rMat_d = xfcapi.makeDetectorRotMat(detectorParams[:3])
    tVec_d = detectorParams[3:6].reshape(3, 1)
    chi    = detectorParams[6]
    tVec_s = detectorParams[7:10].reshape(3, 1)

    rMat_c = xfcapi.makeRotMatOfExpMap(gFull[:3])
    tVec_c = gFull[3:6].reshape(3, 1)
    vInv_s = gFull[6:]
    vMat_s = mutil.vecMVToSymm(vInv_s)              # NOTE: Inverse of V from F = V * R

    gVec_c = np.dot(bMat, hkls_idx)                 # gVecs with magnitudes in CRYSTAL frame
    gVec_s = np.dot(vMat_s, np.dot(rMat_c, gVec_c)) # stretched gVecs in SAMPLE frame
    gHat_c = mutil.unitVector(
        np.dot(rMat_c.T, gVec_s)) # unit reciprocal lattice vectors in CRYSTAL frame

    match_omes, calc_omes = matchOmegas(xyo_det, hkls_idx, chi, rMat_c, bMat, wavelength,
                                        vInv=vInv_s, beamVec=bVec, etaVec=eVec,
                                        omePeriod=omePeriod)

    rMat_s = xfcapi.makeOscillRotMatArray(chi, calc_omes)
    calc_xy = xfcapi.gvecToDetectorXYArray(gHat_c.T,
                                           rMat_d, rMat_s, rMat_c,
                                           tVec_d, tVec_s, tVec_c,
                                           beamVec=bVec)

    if np.any(np.isnan(calc_xy)):
        print "infeasible pFull"

    # return values
    if simOnly:
        retval = np.hstack([calc_xy, calc_omes.reshape(npts, 1)])
    else:
        diff_vecs_xy = calc_xy - xy_unwarped[:, :2]
        diff_ome     = xf.angularDifference( calc_omes, xyo_det[:, 2] )
        retval = np.hstack([diff_vecs_xy,
                            diff_ome.reshape(npts, 1)
                            ]).flatten()
        if return_value_flag == 1:
            retval = sum( abs(retval) )
        elif return_value_flag == 2:
            denom = 3*npts - len(gFit) - 1.
            if denom != 0:
                nu_fac = 1. / denom
            else:
                nu_fac = 1.
            retval = nu_fac * sum(retval**2)
    return retval

# def accept_test(f_new=f_new, x_new=x_new, f_old=fold, x_old=x_old):
#     """
#     """
#     return not np.any(np.isnan(f_new))
