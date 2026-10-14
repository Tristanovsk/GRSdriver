'''
Figures of the documentation: RGB image and Sentinel-2 viewing geometry per band.

Usage: python docs/figures/make_geometry_figures.py <S2 L1C .SAFE> [output directory]
Writes s2_rgb.png, s2_view_azimuth_bands.png, s2_view_zenith_bands.png,
s2_detector_profile.png, s2_azimuth_band_difference.png and, with a zoom box
``lonmin,latmin,lonmax,latmax`` as third argument, s2_sunglint_detectors.png
(default output directory: docs/source/_static).

The figures of the documentation were made with
S2B_MSIL1C_20230711T030529_N0509_R075_T49QDB_20230711T054244.SAFE and the zoom box
110.62,19.15,110.92,19.45.
'''
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import cartopy.crs as ccrs

from GRSdriver import Sentinel2Driver
from GRSdriver.driver_S2_SAFE import INFO

safe = sys.argv[1]
odir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), '..', 'source', '_static')
zoom = [float(v) for v in sys.argv[3].split(',')] if len(sys.argv) > 3 else None
os.makedirs(odir, exist_ok=True)

l1c = Sentinel2Driver(safe, resolution=60, resolution_angle=60)
l1c.load_product()
prod = l1c.prod
tile = prod.attrs['tile']
date = str(prod.time.values)[:10]
title = f'Sentinel-2 L1C, tile {tile}, {date}'

# viewing azimuth, from raa = (vaa - saa) % 360
saa = l1c.raw_sun_ang.sazi.interp(x=prod.x, y=prod.y).astype(np.float32)
prod['vaa'] = (prod.raa + saa) % 360
names = dict(zip(INFO.loc['Wavelength (nm)'].values, INFO.loc['ESA'].values))
labels = [f'{names[int(w)]} ({int(w)} nm)' for w in prod.wl.values]

epsg = l1c.epsg
proj = ccrs.UTM(str(epsg)[-2:], southern_hemisphere=str(epsg)[2] == '7')
cmap = matplotlib.colors.LinearSegmentedColormap.from_list(
    '', ['navy', 'blue', 'lightskyblue', 'gray', 'yellowgreen', 'forestgreen', 'orange', 'red'])
dpi = 110

# 1. RGB
rgb = prod.bands.sel(wl=[665, 560, 490])
fig = plt.figure(figsize=(8, 8))
ax = plt.axes(projection=proj)
(rgb ** 0.6).plot.imshow(ax=ax, rgb='wl', robust=True, transform=proj)
ax.coastlines(resolution='10m', color='w', lw=0.4)
gl = ax.gridlines(draw_labels=True, lw=0.3, color='w', alpha=0.6)
gl.top_labels = gl.right_labels = False
ax.set_title(f'{title}: RGB (B04, B03, B02)')
fig.savefig(os.path.join(odir, 's2_rgb.png'), dpi=dpi, bbox_inches='tight')
plt.close(fig)


# 2-3. viewing azimuth and zenith of each band
def per_band(var, name, unit, fname):
    p = prod[var].assign_coords(wl=labels).plot.imshow(
        col='wl', col_wrap=5, cmap=cmap, robust=True, size=3.2, aspect=1,
        cbar_kwargs=dict(label=f'{name} ({unit})', shrink=0.6))
    for ax in p.axs.flat:
        ax.set_xticks([]); ax.set_yticks([]); ax.set_xlabel(''); ax.set_ylabel('')
        ax.set_aspect('equal')
    p.set_titles('{value}')
    p.fig.suptitle(f'{title}: {name} per band', y=1.01, fontsize=14)
    p.fig.savefig(os.path.join(odir, fname), dpi=dpi, bbox_inches='tight')
    plt.close(p.fig)


per_band('vaa', 'viewing azimuth', 'deg', 's2_view_azimuth_bands.png')
per_band('vza', 'viewing zenith', 'deg', 's2_view_zenith_bands.png')

# 4. across-track profile: odd/even detectors and band dependence
row = prod.y[len(prod.y) // 2]
xkm = (prod.x - prod.x[0]) / 1000
fig, axs = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
colors = plt.cm.Spectral_r(np.linspace(0, 1, len(prod.wl)))
for c, wl, lab in zip(colors, prod.wl.values, labels):
    axs[0].plot(xkm, prod.vaa.sel(wl=wl, y=row), color=c, lw=1, label=lab)
    axs[1].plot(xkm, prod.vza.sel(wl=wl, y=row), color=c, lw=1)
axs[0].set_ylabel('viewing azimuth (deg)')
axs[1].set_ylabel('viewing zenith (deg)')
axs[1].set_xlabel('x (km), tile row at y = %.0f m' % row)
axs[0].legend(fontsize=8, loc='upper left', bbox_to_anchor=(1.01, 1))
axs[0].set_title(f'{title}: across-track profile of the viewing angles')
for ax in axs:
    ax.grid(lw=0.3)
fig.savefig(os.path.join(odir, 's2_detector_profile.png'), dpi=dpi, bbox_inches='tight')
plt.close(fig)

# 5. difference between two bands: odd and even detectors in opposite directions
fig, axs = plt.subplots(1, 3, figsize=(17, 5.5))
det = l1c.get_detector_mask(bandId=1, resolution=60).astype(float)
det[det <= 0] = np.nan
dets = np.unique(det[~np.isnan(det)]).astype(int)
im = axs[0].imshow(det, cmap=plt.cm.get_cmap('tab10', len(dets)), interpolation='nearest',
                   vmin=dets.min() - 0.5, vmax=dets.max() + 0.5)
fig.colorbar(im, ax=axs[0], ticks=dets, shrink=0.8, label='detector number')
axs[0].set_title('detector footprint of B02 (DETFOO)')
for ax, var, name in zip(axs[1:], ('vaa', 'vza'), ('viewing azimuth', 'viewing zenith')):
    diff = prod[var].sel(wl=490) - prod[var].sel(wl=865)
    if var == 'vaa':
        diff = (diff + 180) % 360 - 180
    diff.plot.imshow(ax=ax, cmap=plt.cm.RdBu_r, robust=True, center=0,
                     cbar_kwargs=dict(label='deg', shrink=0.8))
    ax.set_title(f'{name}: B02 - B8A')
for ax in axs:
    ax.set_xticks([]); ax.set_yticks([]); ax.set_xlabel(''); ax.set_ylabel(''); ax.set_aspect('equal')
fig.suptitle(title, fontsize=14)
fig.savefig(os.path.join(odir, 's2_azimuth_band_difference.png'), dpi=dpi, bbox_inches='tight')
plt.close(fig)
# 6. zoom on sunglint: brightness steps at the borders of the detectors
if zoom is not None:
    sub = prod[['bands', 'vaa']].rio.clip_box(*zoom, crs='EPSG:4326')
    det = l1c.get_detector_mask(bandId=11, resolution=60).astype(float)
    det[det <= 0] = np.nan
    import xarray as xr
    det = xr.DataArray(det, coords=dict(y=l1c.new_y, x=l1c.new_x), dims=('y', 'x')).sel(
        x=sub.x, y=sub.y, method='nearest').assign_coords(x=sub.x, y=sub.y)
    fig, axs = plt.subplots(1, 3, figsize=(18, 6), subplot_kw=dict(projection=proj))
    (sub.bands.sel(wl=[665, 560, 490]) ** 0.6).plot.imshow(ax=axs[0], rgb='wl', robust=True, transform=proj)
    axs[0].set_title('RGB (B04, B03, B02)')
    sub.bands.sel(wl=1610).plot.imshow(ax=axs[1], cmap=plt.cm.gray, robust=True, transform=proj,
                                       cbar_kwargs=dict(label='TOA reflectance', shrink=0.7))
    axs[1].set_title('B11 (1610 nm)')
    sub.vaa.sel(wl=1610).plot.imshow(ax=axs[2], cmap=cmap, robust=True, transform=proj,
                                     cbar_kwargs=dict(label='viewing azimuth (deg)', shrink=0.7))
    axs[2].set_title('B11 viewing azimuth')
    for ax in axs:
        det.plot.contour(ax=ax, levels=np.arange(0.5, 13), colors='r', linewidths=0.8, transform=proj,
                         add_labels=False)
        ax.coastlines(resolution='10m', color='y', lw=0.6)
    fig.suptitle(f'{title}: sunglint seen by two detectors (red: detector borders of B11)', fontsize=14)
    fig.savefig(os.path.join(odir, 's2_sunglint_detectors.png'), dpi=dpi, bbox_inches='tight')
    plt.close(fig)
print('figures written in', os.path.abspath(odir))
