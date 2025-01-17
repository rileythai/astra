"""Task for executing FERRE."""

import os
import numpy as np
from itertools import cycle
from typing import Optional, Iterable
from astra.pipelines.ferre import utils
from astra.models.spectrum import Spectrum
from astra.utils import log, dict_to_list, expand_path
from tqdm import tqdm
import warnings

# FERRE v4.8.8 src trunk : /uufs/chpc.utah.edu/common/home/sdss09/software/apogee/Linux/apogee/trunk/external/ferre/src


def pre_process_ferre(
    pwd: str,
    header_path: str,
    spectra: Iterable[Spectrum],
    initial_teff: Iterable[float],
    initial_logg: Iterable[float],
    initial_m_h: Iterable[float],
    initial_log10_v_sini: Iterable[float] = None,
    initial_log10_v_micro: Iterable[float] = None,
    initial_alpha_m: Iterable[float] = None,
    initial_c_m: Iterable[float] = None,
    initial_n_m: Iterable[float] = None,
    initial_flags: Iterable[str] = None,
    upstream_pk: Iterable[int] = None,
    frozen_parameters: Optional[dict] = None,
    interpolation_order: int = 3,
    weight_path: Optional[str] = None,
    lsf_shape_path: Optional[str] = None,
    lsf_shape_flag: int = 0,
    error_algorithm_flag: int = 1,
    wavelength_interpolation_flag: int = 0,
    optimization_algorithm_flag: int = 3,
    pre_computed_continuum: Optional[Iterable[float]] = None,
    continuum_flag: int = 1,
    continuum_order: int = 4,
    continuum_segment: Optional[int] = None,
    continuum_reject: float = 0.3,
    continuum_observations_flag: int = 1,
    full_covariance: bool = True,
    pca_project: bool = False,
    pca_chi: bool = False,
    f_access: int = 0,
    f_format: int = 1,
    ferre_kwds: Optional[dict] = None,
    n_threads: int = 32,
    bad_pixel_flux_value: float = 1e-4,
    bad_pixel_error_value: float = 1e10,
    skyline_sigma_multiplier: float = 100,
    min_sigma_value: float = 0.05,
    spike_threshold_to_inflate_uncertainty: float = 3,
    reference_pixel_arrays_for_abundance_run=False,
    write_input_pixel_arrays=True,
    **kwargs
):
    
    if kwargs:
        log.warning(f"astra.pipelines.ferre.pre_process.pre_process ignoring kwargs: {kwargs}")

    # Validate the control file keywords.
    (
        control_kwds,
        headers,
        segment_headers,
        frozen_parameters,
    ) = utils.validate_ferre_control_keywords(
        header_path=header_path,
        frozen_parameters=frozen_parameters,
        interpolation_order=interpolation_order,
        weight_path=weight_path,
        lsf_shape_path=lsf_shape_path,
        lsf_shape_flag=lsf_shape_flag,
        error_algorithm_flag=error_algorithm_flag,
        wavelength_interpolation_flag=wavelength_interpolation_flag,
        optimization_algorithm_flag=optimization_algorithm_flag,
        continuum_flag=continuum_flag,
        continuum_order=continuum_order,
        continuum_segment=continuum_segment,
        continuum_reject=continuum_reject,
        continuum_observations_flag=continuum_observations_flag,
        full_covariance=full_covariance,
        pca_project=pca_project,
        pca_chi=pca_chi,
        n_threads=n_threads,
        f_access=f_access,
        f_format=f_format,
    )

    # Include any explicitly set ferre kwds
    control_kwds.update(ferre_kwds or dict())

    if reference_pixel_arrays_for_abundance_run:
        prefix = os.path.basename(pwd.rstrip("/")) + "/"
        for key in ("pfile", "opfile", "offile", "sffile"):
            control_kwds[key] = prefix + control_kwds[key]

    absolute_pwd = expand_path(pwd)
    log.info(f"FERRE working directory: {absolute_pwd}")


    # Construct mask to match FERRE model grid.
    #chip_wavelengths = tuple(map(utils.wavelength_array, segment_headers))
    
    values_or_cycle_none = lambda x: x if (x is not None and len(x) > 0) else cycle([None])
    all_initial_parameters = dict_to_list(dict(
        teff=values_or_cycle_none(initial_teff),
        logg=values_or_cycle_none(initial_logg),
        m_h=values_or_cycle_none(initial_m_h),
        log10_v_sini=values_or_cycle_none(initial_log10_v_sini),
        log10_v_micro=values_or_cycle_none(initial_log10_v_micro),
        alpha_m=values_or_cycle_none(initial_alpha_m),
        c_m=values_or_cycle_none(initial_c_m),
        n_m=values_or_cycle_none(initial_n_m),
        initial_flags=values_or_cycle_none(initial_flags),
        upstream_pk=values_or_cycle_none(upstream_pk)
    ))

    # Retrict to the pixels within the model wavelength grid.
    # TODO: Assuming all spectra are the same.
    #mask = _get_ferre_chip_mask(spectra[0].wavelength, chip_wavelengths)

    # TODO: use mask2
    mask = utils.get_apogee_pixel_mask()
    #assert np.all(mask == mask2)

    index, skipped, batch_names, batch_initial_parameters, batch_flux, batch_e_flux = (0, [], [], [], [], [])
    for (spectrum, initial_parameters) in tqdm(zip(spectra, all_initial_parameters), total=1, desc="Preparing spectra"):

        if spectrum in skipped:
            continue

        if write_input_pixel_arrays:
            # We usually will be writing input pixel arrays, but sometimes we won't
            # (e.g., one other abundances execution has written the input pixel arrays
            # and this one could just be referencing them)

            # If this part fails, the spectrum doesn't exist and we should just continue
            try:
                flux = np.copy(spectrum.flux)
                e_flux = np.copy(spectrum.ivar)**-0.5
            except (ValueError, FileNotFoundError):
                log.warning(f"Exception accessing pixel arrays for spectrum {spectrum}")
                skipped.append(spectrum)
                continue            

            try:
                pixel_flags = np.copy(spectrum.pixel_flags)
            except AttributeError:
                warnings.warn(f"At least one spectrum has no pixel_flags attribute")

            else:
                # TODO: move this to the ASPCAP coarse/stellar parameter section (before continuum norm).
                flux, e_flux = inflate_errors_at_bad_pixels(
                    flux,
                    e_flux,
                    pixel_flags,
                    skyline_sigma_multiplier=skyline_sigma_multiplier,
                    bad_pixel_flux_value=bad_pixel_flux_value,
                    bad_pixel_error_value=bad_pixel_error_value,
                    spike_threshold_to_inflate_uncertainty=spike_threshold_to_inflate_uncertainty,
                    min_sigma_value=min_sigma_value,
                )

            if pre_computed_continuum is not None:
                flux /= pre_computed_continuum[index]
                e_flux /= pre_computed_continuum[index]
            
            batch_flux.append(flux[mask])
            batch_e_flux.append(e_flux[mask])

        # make the initial flags 0 if None is given
        initial_flags = initial_parameters.pop("initial_flags") or 0
        upstream_pk = initial_parameters.pop("upstream_pk")

        batch_names.append(utils.get_ferre_spectrum_name(index, spectrum.source_pk, spectrum.spectrum_pk, initial_flags, upstream_pk))
        batch_initial_parameters.append(initial_parameters)
        index += 1

    if not batch_initial_parameters:
        return (pwd, 0, skipped)

    control_kwds_formatted = utils.format_ferre_control_keywords(control_kwds, n_obj=1 + index)
    log.info(f"FERRE control keywords:\n{control_kwds_formatted}")

    # Convert list of dicts of initial parameters to array.
    log.info(f"Validating initial and frozen parameters")
    batch_initial_parameters_array = utils.validate_initial_and_frozen_parameters(
        headers,
        batch_initial_parameters,
        frozen_parameters,
        clip_initial_parameters_to_boundary_edges=True,
        clip_epsilon_percent=1,
    )
    # Create directory and write the control file        
    os.makedirs(absolute_pwd, exist_ok=True)
    log.info(f"Writing control file")
    with open(os.path.join(absolute_pwd, "input.nml"), "w") as fp:
        fp.write(control_kwds_formatted)       

    # hack: we do basename here in case we wrote the prefix to PFILE for the abundances run
    log.info(f"Writing input parameters")
    with open(os.path.join(absolute_pwd, os.path.basename(control_kwds["pfile"])), "w") as fp:
        for name, point in zip(batch_names, batch_initial_parameters_array):
            fp.write(utils.format_ferre_input_parameters(*point, name=name))

    if write_input_pixel_arrays:
        log.info(f"Writing input pixel arrays")
        LARGE = 1e10

        batch_flux = np.array(batch_flux)
        batch_e_flux = np.array(batch_e_flux)

        if reference_pixel_arrays_for_abundance_run:
            flux_path = os.path.join(absolute_pwd, "../", control_kwds["ffile"])
            e_flux_path = os.path.join(absolute_pwd, "../", control_kwds["erfile"])
        else:
            flux_path = os.path.join(absolute_pwd, control_kwds["ffile"])
            e_flux_path = os.path.join(absolute_pwd, control_kwds["erfile"])

        non_finite_flux = ~np.isfinite(batch_flux)
        batch_flux[non_finite_flux] = 0.0
        batch_e_flux[non_finite_flux] = LARGE
        if np.any(non_finite_flux):
            log.warning(f"Non-finite fluxes found. Setting them to zero and setting flux error to {LARGE:.1e}")

        finite_e_flux = np.isfinite(batch_e_flux)
        batch_e_flux[~finite_e_flux] = LARGE
        if not np.any(finite_e_flux):
            log.warning(f"ALL flux errors are non-finite!")
            
        # Write data arrays.
        savetxt_kwds = dict(fmt="%.4e")#footer="\n")
        np.savetxt(flux_path, batch_flux, **savetxt_kwds)
        np.savetxt(e_flux_path, batch_e_flux, **savetxt_kwds)
        
    n_obj = len(batch_names)
    return (pwd, n_obj, skipped)



def inflate_errors_at_bad_pixels(
    flux,
    e_flux,
    bitfield,
    skyline_sigma_multiplier,
    bad_pixel_flux_value,
    bad_pixel_error_value,
    spike_threshold_to_inflate_uncertainty,
    min_sigma_value,
):
    # Inflate errors around skylines,
    skyline_mask = (bitfield & 4096) > 0 # significant skyline
    e_flux[skyline_mask] *= skyline_sigma_multiplier

    # Sometimes FERRE will run forever.
    if spike_threshold_to_inflate_uncertainty > 0:

        flux_median = np.nanmedian(flux)
        flux_stddev = np.nanstd(flux)
        e_flux_median = np.median(e_flux)

        delta = (flux - flux_median) / flux_stddev
        is_spike = (delta > spike_threshold_to_inflate_uncertainty)
        #* (
        #    sigma_ < (parameters["spike_threshold_to_inflate_uncertainty"] * e_flux_median)
        #)
        #if np.any(is_spike):
        #    sum_spike = np.sum(is_spike)
            #fraction = sum_spike / is_spike.size
            #log.warning(
            #    f"Inflating uncertainties for {sum_spike} pixels ({100 * fraction:.2f}%) that were identified as spikes."
            #)
            #for pi in range(is_spike.shape[0]):
            #    n = np.sum(is_spike[pi])
            #    if n > 0:
            #        log.debug(f"  {n} pixels on spectrum index {pi}")
        e_flux[is_spike] = bad_pixel_error_value

    # Set bad pixels to have no useful data.
    if bad_pixel_flux_value is not None or bad_pixel_error_value is not None:                            
        bad = (
            ~np.isfinite(flux)
            | ~np.isfinite(e_flux)
            | (flux < 0)
            | (e_flux < 0)
            | ((bitfield & 16639) > 0) # any bad value (level = 1)
        )

        flux[bad] = bad_pixel_flux_value
        e_flux[bad] = bad_pixel_error_value        

    if min_sigma_value is not None:
        e_flux = np.clip(e_flux, min_sigma_value, np.inf)

    return (flux, e_flux)


def _get_ferre_chip_mask(observed_wavelength, chip_wavelengths):
    P = observed_wavelength.size
    mask = np.zeros(P, dtype=bool)
    for model_wavelength in chip_wavelengths:
        s_index = observed_wavelength.searchsorted(model_wavelength[0])
        e_index = s_index + model_wavelength.size
        mask[s_index:e_index] = True
    return mask                    