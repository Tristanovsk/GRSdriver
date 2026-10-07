Methods
=======

This page describes how the drivers compute the variables of the loaded product
(``prod``): top-of-atmosphere reflectance, central wavelengths and sun/viewing geometry.
Notation:

- :math:`(x, y)`: pixel coordinates in the projected CRS of the product (m);
- :math:`\lambda`: wavelength (nm), :math:`b` a spectral band, :math:`d` a detector;
- :math:`\theta_s, \phi_s`: solar zenith and azimuth angles;
- :math:`\theta_v, \phi_v`: viewing zenith and azimuth angles.

All the angles are in degrees.


Top-of-atmosphere reflectance
-----------------------------

The bands are read with `EOReader <https://eoreader.readthedocs.io>`__, which converts the
digital counts into top-of-atmosphere (TOA) reflectance.

Sentinel-2 L1C
~~~~~~~~~~~~~~

The L1C digital numbers :math:`DN_b` are converted with the quantification value
(:math:`Q = 10000`) and, since processing baseline 04.00, the radiometric offset
:math:`O_b` (:math:`-1000`) of the product metadata:

.. math::

    \rho_b(x, y) = \frac{DN_b(x, y) + O_b}{Q}

Landsat 8/9 Collection 2 Level-1
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The quantized values :math:`Q_{cal}` are rescaled with the coefficients of the metadata
(``REFLECTANCE_MULT_BAND_b``, ``REFLECTANCE_ADD_BAND_b``) into a reflectance that is not yet
corrected for the solar zenith angle; the driver applies this correction to the
vis-NIR-SWIR bands (:math:`\lambda \leq 3000` nm):

.. math::

    \rho_b(x, y) = \frac{M_{\rho, b}\, Q_{cal, b}(x, y) + A_{\rho, b}}{\cos \theta_s(x, y)}

The thermal bands (TIR_1, TIR_2) are given as brightness temperature (K), from the
TOA radiance :math:`L_b` and the thermal constants :math:`K_{1,b}, K_{2,b}` of the metadata:

.. math::

    T_b(x, y) = \frac{K_{2,b}}{\ln\left(\dfrac{K_{1,b}}{L_b(x, y)} + 1\right)}


Central wavelengths
-------------------

``SRF`` (wl, wl_hr) holds the spectral response function :math:`S_b(\lambda)` of each band
on a 1 nm grid (Sentinel-2: from the L1C metadata; Landsat: files shipped with GRSdriver).
The central wavelength ``wl_true`` is the SRF-weighted mean wavelength:

.. math::

    \lambda_b = \frac{\displaystyle\int \lambda\, S_b(\lambda)\, \mathrm{d}\lambda}
                     {\displaystyle\int S_b(\lambda)\, \mathrm{d}\lambda}

computed with the trapezoidal rule over the defined values of :math:`S_b`. The ``wl``
coordinate keeps the nominal wavelength of each band.


Sentinel-2 geometry
-------------------

The granule metadata (``MTD_TL.xml``) gives the angles on a coarse grid of
:math:`23 \times 23` nodes (5 km spacing): one grid for the sun angles, and one grid per band
and per detector for the viewing angles, each detector covering only a strip of the tile.
The angles are computed on the ``resolution_angle`` grid (10, 20 or 60 m), then resampled
onto the grid of the bands (see `Resampling onto the band grid`_).

Sun angles
~~~~~~~~~~

The sun angles vary smoothly over the tile: :math:`\theta_s` and :math:`\phi_s` are
bilinearly interpolated from the four surrounding nodes :math:`(x_i, y_j)`:

.. math::

    \theta_s(x, y) = \sum_{i, j \in \{0, 1\}} w_i(x)\, w_j(y)\, \theta_s(x_i, y_j)

.. math::

    w_1(x) = \frac{x - x_0}{x_1 - x_0}, \qquad w_0(x) = 1 - w_1(x)

and similarly for :math:`w_j(y)` and :math:`\phi_s`.

Viewing angles
~~~~~~~~~~~~~~

The viewing angles are discontinuous at the borders between detectors, so that a direct
interpolation of the 5 km grids would be wrong in the overlap of two detectors. Instead,
for each band :math:`b` and each detector :math:`d`, the angle :math:`\alpha`
(:math:`\theta_v` or :math:`\phi_v`) is modelled as a plane:

.. math::

    \alpha_{b,d}(x, y) = \beta_{0}\, x + \beta_{1}\, y + \beta_{2}

The coefficients :math:`\boldsymbol\beta_{b,d} = (\beta_0, \beta_1, \beta_2)` are fitted on the
:math:`n` valid nodes :math:`(x_k, y_k, \alpha_k)` of the detector grid (NaN nodes removed) by
orthogonal distance regression (``scipy.odr``), which minimizes the sum of squared orthogonal
distances between the nodes and the plane, i.e. accounts for errors on the coordinates
:math:`\mathbf{p}_k = (x_k, y_k)` as well as on the angles:

.. math::

    \hat{\boldsymbol\beta}_{b,d} = \arg\min_{\boldsymbol\beta,\, \boldsymbol\delta}
    \sum_{k=1}^{n} \Big[ \big(\alpha_k - \alpha(\mathbf{p}_k + \boldsymbol\delta_k;
    \boldsymbol\beta)\big)^2 + \lVert \boldsymbol\delta_k \rVert^2 \Big]

starting from :math:`\boldsymbol\beta = (0, 0, \bar\alpha)`.

The detector footprint mask (``DETFOO``) of the L1C product gives the detector
:math:`D_b(x, y)` that sees each pixel. The angle of a pixel is the plane of that detector:

.. math::

    \alpha_b(x, y) = \alpha_{b, D_b(x, y)}(x, y)

Pixels seen by no detector (outside the swath) are set to NaN. This evaluation is compiled
with numba and done in float32.

Relative azimuth
~~~~~~~~~~~~~~~~

.. math::

    \phi_b(x, y) = \big(\phi_{v,b}(x, y) - \phi_s(x, y)\big) \bmod 360

Variables: ``sza`` = :math:`\theta_s` (y, x); ``vza`` = :math:`\theta_{v,b}` and
``raa`` = :math:`\phi_b` (wl, y, x).


Landsat geometry
----------------

The angles are read from the angle GeoTIFFs of the product (``*_SZA.TIF``, ``*_SAA.TIF``,
``*_VZA.TIF``, ``*_VAA.TIF``), stored as integers :math:`I` in hundredths of degree
(0 = no data):

.. math::

    \alpha(x, y) = 0.01\, I(x, y)

They are not band specific: ``sza``, ``vza`` and ``raa`` are (y, x) arrays, with the
relative azimuth

.. math::

    \phi(x, y) = \phi_s(x, y) - \phi_v(x, y)

(note the convention, opposite to the one of the Sentinel-2 driver, and without modulo).
When the bands are loaded at another resolution or on a subset, the angles are bilinearly
interpolated onto the grid of the bands, and the L1 bitmask ``flags_l1`` is resampled by
nearest neighbour.


Resampling onto the band grid
-----------------------------

For Sentinel-2, the angles computed at ``resolution_angle`` are put on the band grid
(``resolution``, possibly a subset) by nearest neighbour. For a band pixel center
:math:`(x, y)`, the source pixel is

.. math::

    i(x) = \arg\min_{i} |x - x_i|, \qquad j(y) = \arg\min_{j} |y - y_j|

where :math:`x_i, y_j` are the coordinates of the angle grid; the lookup is a plain
array indexing :math:`\alpha(x, y) = A[j(y), i(x)]`, separable in :math:`x` and :math:`y`.


Scattering angle
----------------

Both drivers provide ``scat_angle`` to compute the scattering angle :math:`\Theta` from
the sun and viewing angles, with the relative azimuth :math:`\phi` defined such that
:math:`\phi = 180^\circ` when the sun and the sensor are in opposition (backscattering
geometry when :math:`\theta_v = \theta_s`):

.. math::

    \cos \Theta = -\cos\theta_s \cos\theta_v - \sin\theta_s \sin\theta_v \cos\phi


Memory footprint
----------------

Each float32 variable of dimensions (wl, y, x) needs

.. math::

    M = 4\, N_\lambda\, N_y\, N_x \ \text{bytes}

For a full Sentinel-2 tile (:math:`N_\lambda = 13` bands; :math:`N_y = N_x = 5490` at
20 m, :math:`10980` at 10 m), ``bands``, ``vza`` and ``raa`` take 1.57 GB each at 20 m and
6.3 GB each at 10 m.

Two options reduce the memory used by the Sentinel-2 driver:

- the bands are loaded one by one into a preallocated array, so that the loading needs
  about the size of the final ``bands`` array plus the temporaries of one band;
- with ``lazy_geom=True``, ``vza`` and ``raa`` are dask arrays: each block is looked up in the
  ``resolution_angle`` grid of :math:`N_y' \times N_x'` pixels (:math:`4 N_\lambda N_y' N_x'` bytes
  per variable, e.g. 0.17 GB at 60 m)
  only when it is computed, so that the :math:`2 \times 4 N_\lambda N_y N_x` bytes of the
  full-resolution angles are never allocated (3.1 GB at 20 m, 12.5 GB at 10 m).

.. code-block:: python

    from GRSdriver import Sentinel2Driver

    l1c = Sentinel2Driver('S2A_MSIL1C_..._.SAFE',
                          resolution=20, lazy_geom=True)
    l1c.load_product()
    # dask array, computed by blocks of geom_chunks x geom_chunks pixels
    l1c.prod.vza

Measured peak memory for a full tile (13 bands, 20 m): 7.0 GB with the full-resolution
angles, 3.7 GB with ``lazy_geom=True``.
