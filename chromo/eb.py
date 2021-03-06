import numpy as np
import matplotlib.pyplot as plt
import os
from tqdm import tqdm
from copy import deepcopy
import logging
import warnings

from astropy.stats import sigma_clipped_stats, sigma_clip
from astropy.convolution import convolve, Box1DKernel, Box2DKernel, Gaussian2DKernel
from astropy.io import fits

import lightkurve as lk

from .utils import *

log = logging.getLogger(__name__)
log.setLevel('INFO')


plt.style.use(lk.MPLSTYLE)

def analyze(raw_tpf, period, t0, name='target', aper=None, nb=100):
    '''
    '''

    # Find saturated pixels
    saturated = np.nanmax(raw_tpf.flux, axis=0) > 100000
    for idx, s in enumerate(saturated.T):
        saturated[:, idx] = (convolve(s, Box1DKernel(5)) > 1e-5)

    saturated |= np.nanmax(raw_tpf.flux, axis=0) > 50000
    for idx, s in enumerate(saturated.T):
        saturated[:, idx] = (convolve(s, Box1DKernel(10)) > 1e-5)

    if aper is None:
        aper = np.ones(raw_tpf.shape[1:], bool)

    true = raw_tpf.to_lightcurve(aperture_mask=aper).normalize()

    tpf = background_correct(raw_tpf)

    true = tpf.to_lightcurve(aperture_mask=aper).normalize()
    x_fold = (true.time - t0 - period/2) / period % 1 - 0.5


    true_primary_depth = np.nanmedian(true.flux[np.abs(x_fold) < 0.02])
    true_secondary_depth = np.nanmedian(true.flux[np.abs(x_fold) > 0.48])

#    fig, ax = plt.subplots()
#    ax.plot(x_fold[np.argsort(x_fold)], true.flux[np.argsort(x_fold)])
#    ax.axhline(true_primary_depth, color='C1', ls='--', label='Secondary Depth')
#    ax.axhline(true_secondary_depth, color='C2', ls=':', label='Primary Depth')
#    ax.legend()

    time = deepcopy(tpf.time)
    flux = deepcopy(tpf.flux)
    flux_err = deepcopy(tpf.flux)
    true_flux = deepcopy(true.flux)

    data = np.zeros(flux.shape)
    model = np.zeros(flux.shape)

    primary_depth = np.zeros(flux.shape[1:])
    secondary_depth = np.zeros(flux.shape[1:])

    primary_depth_err = np.zeros(flux.shape[1:])
    secondary_depth_err = np.zeros(flux.shape[1:])


    for jdx in tqdm(range(flux.shape[2]), desc='Calculating Pixel Light Curves'):
        for idx in range(flux.shape[1]):
            # BUILD a lk object
            l1 = lk.LightCurve(time, flux[:, idx, jdx], flux_err=flux_err[:, idx, jdx])
            # Detrend long term
            l1 /= poly_detrend(l1).flux
            l1 = l1.normalize()
            primary_depth[idx, jdx] = np.nanmedian(l1.flux[np.abs(x_fold) < 0.02])
            primary_depth_err[idx, jdx] = np.nanstd(l1.flux[np.abs(x_fold) < 0.02])

            secondary_depth[idx, jdx] = np.nanmedian(l1.flux[np.abs(x_fold) > 0.48])
            secondary_depth_err[idx, jdx] = np.nanstd(l1.flux[np.abs(x_fold) > 0.48])

#            d = (1 - primary_depth[idx, jdx])/(1 - true_primary_depth)
#            model_flux[:, idx, jdx] = true_flux/((1/d) - (1/d) + 1)

            data[:, idx, jdx] = l1.flux

            p = 1 - np.nanmedian(l1.normalize().flux[np.abs(x_fold) < 0.02])
            tp = 1 - np.nanmedian(true_flux[np.abs(x_fold) < 0.02])
            corr = (p/tp)
            corr_model_lc =  (true_flux) * corr - corr + 1
            model[:, idx, jdx] = corr_model_lc


    primary_depth[saturated] = np.nan
    secondary_depth[saturated] = np.nan
#    aper = (np.nan_to_num(primary_depth) < 0.95) & ~saturated


    inds = np.array_split(np.argsort(x_fold), np.linspace(0, len(x_fold), nb + 1, dtype=int))[1:-1]
    x_fold_b = np.asarray([np.median(x_fold[ind]) for ind in inds])
    data_b = np.asarray([np.median(data[ind, :, :], axis=0) for ind in inds])
    model_b = np.asarray([np.median(model[ind, :, :], axis=0) for ind in inds])
    true_flux_b = np.asarray([np.median(true.flux[ind]) for ind in inds])
    true_flux_b /= np.nanmedian(true_flux)

    resids = data_b - np.atleast_3d(np.median(data, axis=0)).transpose([2, 0, 1])
    resids -= (np.copy(model_b) -  np.atleast_3d(np.median(model, axis=0)).transpose([2, 0, 1]))

    ph, fl = x_fold_b[np.argsort(x_fold_b)], true_flux_b[np.argsort(x_fold_b)]

    log.info('\tBuilding Normalized Flux Animation')
    color_aper = (model_b[nb//2] < 0.99) & ~saturated
    fmin, fmax = np.nanpercentile(model_b[:, color_aper], 1), np.nanmax([1, np.nanpercentile(model_b[:, color_aper], 1)])
    print(fmin, fmax)
    plt.imshow(color_aper)
    return
    movie(data_b, ph, fl, cmap='viridis', vmin=fmin, vmax=fmax, out='{}.mp4'.format(name.replace(' ', '')),
                       title='Normalized Data', cbar_label='Normalized Flux')

    return
    cmap = plt.get_cmap('PuOr_r')
    color_aper = ((model_b[nb//2] < 0.99) & (model_b[nb//2] > fmin*0.5)) & ~saturated
    vmin, vmax = np.min([0, np.nanpercentile(resids[:, color_aper], 1)]), np.nanmax([0, np.nanpercentile(resids[:, color_aper], 99)])

    vmax = np.max([np.abs(vmin), vmax])
    vmin = -vmax

    log.info('\tBuilding Residual Flux Animation')
    norm = MidPointNorm(midpoint=0, vmin=vmin, vmax=vmax)
    cmap.set_bad('lightgrey', 0)

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        movie(resids/np.atleast_3d(aper & ~saturated).transpose([2, 0, 1]), ph, fl,
                           cmap=cmap, norm=norm, vmin=vmin, vmax=vmax, out='{}_resids.mp4'.format(name.replace(' ', '')),
                           title='Residuals', cbar_label='Resiudal')

    return

    plt.figure()
    plt.plot(x_fold, data[:, aper], 'k.', alpha=0.01);
    plt.plot(x_fold[np.argsort(x_fold)], true.flux[np.argsort(x_fold)], c='r')
    plt.ylim(0, 1.5)


    all_aper = np.ones(flux.shape[1:], bool)
    norm_depth_ratio = secondary_depth/primary_depth - true_secondary_depth/true_primary_depth
    plt.figure()
    plt.hist(norm_depth_ratio[np.isfinite(norm_depth_ratio)], np.linspace(-0.3, 0.3, 50));
    plt.yscale('log')


    cmap = plt.get_cmap('RdBu')
    norm = MidPointNorm(midpoint=0, vmin=np.min([0, np.nanmin(norm_depth_ratio)]), vmax=np.nanmax([0, np.nanmax(norm_depth_ratio)]))
    cmap.set_bad('lightgrey', 1)




    # Matplot lib stuff
    fig, ax = plt.subplots(figsize=(17, 8))

    for l, n in zip(deepcopy(data_b[:, aper].T), norm_depth_ratio[aper]):
#        d = (1 - p)/(1 - true_primary_depth)
#        l2 = (l * (1/d) - (1/d) + 1)
        l /= np.median(l)
        p = 1 - np.nanmedian(l[np.abs(x_fold_b) < 0.02])
        tp = 1 - np.nanmedian(true_flux_b[np.abs(x_fold_b) < 0.02])
#        ax.scatter(0, p, c='k')
        corr = (p/tp)
        ax.plot(x_fold_b, l * (1/corr) - (1/corr) + 1, color=cmap(norm(n)), zorder=n)
        #ax.plot(x_fold_b, (true_flux_b) * corr - corr + 1, color='k', zorder=n)

    #Horrible Colorbar
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax)
    #cbar.set_label('Measured Secondary Depth/\nTrue Secondary Depth')
    ax.set_ylabel('Pixel Light Curves')
    ax.axvline(0, ls='--', color='k')

#    return norm_depth_ratio


    # Matplot lib stuff
    fig, ax = plt.subplots(figsize=(17, 8))
    for l, n in zip(deepcopy(data_b[:, aper].T), norm_depth_ratio[aper]):
#        d = (1 - p)/(1 - true_primary_depth)
#        l2 = (l * (1/d) - (1/d) + 1)
        l /= np.median(l)
        p = 1 - np.nanmedian(l[np.abs(x_fold_b) < 0.02])
        tp = 1 - np.nanmedian(true_flux_b[np.abs(x_fold_b) < 0.02])
#        ax.scatter(0, p, c='k')
        corr = (p/tp)
        corr_lc =  (true_flux_b) * corr - corr + 1
        ax.plot(x_fold_b, l - corr_lc, color=cmap(norm(n)), zorder=n)
        #ax.plot(x_fold_b, (true_flux_b) * corr - corr + 1, color='k', zorder=n)

    #Horrible Colorbar
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax)
    #cbar.set_label('Measured Secondary Depth/\nTrue Secondary Depth')
    ax.set_ylabel('Pixel Light Curves')
    ax.axvline(0, ls='--', color='k')




    # Matplot lib stuff
    fig, ax = plt.subplots(figsize=(17, 8))

    for l, n in zip(deepcopy(data_b[:, aper].T), norm_depth_ratio[aper]):
#        d = (1 - p)/(1 - true_primary_depth)
#        l2 = (l * (1/d) - (1/d) + 1)
        l /= np.median(l)
        p = 1 - np.nanmedian(l[np.abs(x_fold_b) < 0.02])
        tp = 1 - np.nanmedian(true_flux_b[np.abs(x_fold_b) < 0.02])
#        ax.scatter(0, p, c='k')
        corr = (p/tp)
        corr_lc =  (true_flux_b) * corr - corr + 1

        x, y = np.hstack([x_fold_b, x_fold_b + 1]), np.hstack([l - corr_lc, l - corr_lc])
        ax.plot(x, y, color=cmap(norm(n)), zorder=n)
        #ax.plot(x_fold_b, (true_flux_b) * corr - corr + 1, color='k', zorder=n)

    #Horrible Colorbar
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax)
    #cbar.set_label('Measured Secondary Depth/\nTrue Secondary Depth')
    ax.set_ylabel('Pixel Light Curves')
    ax.axvline(0.5, ls='--', color='k')
    ax.set_xlim(0, 1)

    return data_b, true_flux_b
