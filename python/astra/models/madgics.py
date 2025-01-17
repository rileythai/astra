import numpy as np
import h5py
import concurrent
from peewee import (
    AutoField,
    ForeignKeyField,
    IntegerField,
    TextField
)
from tqdm import tqdm
from astra.models.base import BaseModel
from astra.models.source import Source
from astra.models.spectrum import (Spectrum, SpectrumMixin)
from astra.models.fields import PixelArray, PixelArrayAccessorHDF, LogLambdaArrayAccessor
from astra.specutils.resampling import wave_to_pixel, sincint

from astra.glossary import Glossary
from astra.models.apogee import ApogeeVisitSpectrum


class ApogeeMADGICSVisitSpectrum(BaseModel, SpectrumMixin):

    """An APOGEE spectrum from the MADGICS pipeline."""

    pk = AutoField()
    
    #> Identifiers
    spectrum_pk = ForeignKeyField(
        Spectrum,
        null=True,
        index=True,
        unique=True,
        lazy_load=False,
    )
    drp_spectrum_pk = ForeignKeyField(
        ApogeeVisitSpectrum,
        index=True,
        unique=True,
        lazy_load=False,
        field=ApogeeVisitSpectrum.spectrum_pk,
        help_text=Glossary.drp_spectrum_pk
    )    
    source = ForeignKeyField(
        Source, 
        null=True, 
        index=True,
        column_name="source_pk",
        backref="apogee_madgics_spectra",
    )

    wavelength = PixelArray(
        accessor_class=LogLambdaArrayAccessor,
        accessor_kwargs=dict(
            crval=4.179,
            cdelt=6e-6,
            naxis=8575,
        ),
        help_text=Glossary.wavelength
    )
    '''
    flux = PixelArray(
        column_name="x_starLines_v0",
        transform=lambda x: 1 + x[125:]
    )
    ivar = PixelArray(
        column_name="x_starLines_err_v0",
        accessor_class=PixelArrayAccessorHDF,
        transform=lambda x: x[125:]**-2
    )

    row_index = IntegerField(index=True)
    v_rad_pixel = PixelArray(column_name="RV_pixoff_final", accessor_class=PixelArrayAccessorHDF)
    '''


    release = TextField()
    telescope = TextField()
    field = TextField()
    plate = IntegerField()
    mjd = IntegerField()
    fiber = IntegerField()

    class Meta:
        indexes = (
            (
                (
                    "release",
                    "telescope",
                    "field",
                    "plate",
                    "mjd",
                    "fiber",
                ),
                True,
            ),
        )


    @property
    def path(self):
        raise a
    



def resample_apmadgics(spectrum, n_res):       
    x = np.arange(spectrum.wavelength.size) 

    pixel = wave_to_pixel(x + spectrum.v_rad_pixel, x)
    (finite, ) = np.where(np.isfinite(pixel))

    ((finite_flux, finite_e_flux), ) = sincint(
        pixel[finite], n_res, [
            [spectrum.flux, 1/spectrum.ivar]
        ]
    )

    flux = np.nan * np.ones(spectrum.wavelength.size)
    e_flux = np.nan * np.ones(spectrum.wavelength.size)
    flux[finite] = finite_flux
    e_flux[finite] = finite_e_flux
    
    spectrum.flux = flux
    spectrum.ivar = e_flux**-2
    bad = ~np.isfinite(spectrum.ivar)
    spectrum.ivar[bad] = 0
    
    return None


def _shift_and_resample_to_rest_frame(index, v_rad, flux, flux_var, n_res=4.25):
    x = np.arange(flux.size)
    pixel = wave_to_pixel(x + v_rad, x)

    (finite, ) = np.where(np.isfinite(pixel))

    ((finite_flux, finite_e_flux), ) = sincint(
        pixel[finite], n_res, [
            [flux, flux_var]
        ]
    )

    finite_ivar = finite_e_flux**-2
    finite_ivar[~np.isfinite(finite_ivar)] = 0

    resampled_flux = np.zeros_like(flux)
    resampled_ivar = np.zeros_like(flux)
    resampled_flux[finite] = finite_flux
    resampled_ivar[finite] = finite_ivar

    return (index, resampled_flux, resampled_ivar)


def shift_and_resample_to_rest_frame(flux_path, flux_err_path, rv_pixoff_path, n_res=4.25, max_workers=4):
    import os
    print("loading flux")
    flux_fp = h5py.File(flux_path, "r")
    print("loading err")
    flux_err_fp = h5py.File(flux_err_path, "r")
    print("loading rv")
    rv_pixoff_fp = h5py.File(rv_pixoff_path, "r")
    get_key = lambda x: os.path.basename(x).split(".")[0][14:] 

    print("parsing vrads")
    v_rads = rv_pixoff_fp[get_key(rv_pixoff_path)]
    print("parsing fluxes")
    fluxes = flux_fp[get_key(flux_path)]
    print("parsing vars")
    e_fluxes = flux_err_fp[get_key(flux_err_path)]
    print("done")

    N, P = flux_fp[get_key(flux_path)].shape
    
    executor = concurrent.futures.ProcessPoolExecutor(max_workers)

    futures = []
    for i, (v_rad, flux, e_flux) in enumerate(tqdm(zip(v_rads, fluxes, e_fluxes), total=N, desc="Submitting")):
        futures.append(
            executor.submit(_shift_and_resample_to_rest_frame, i, v_rad, 1 + flux, e_flux**2, n_res)
        )

    print("preparing flux array")
    resampled_fluxs = np.zeros((N, P), dtype=float)
    print("prepareing ivar array")
    resampled_ivars = np.zeros((N, P), dtype=float)
    print("ok")

    with tqdm(total=N, desc="Resampling in parallel") as pb:
        for future in concurrent.futures.as_completed(futures):
            index, resampled_flux, resampled_ivar = future.result()
            resampled_fluxs[index] = resampled_flux
            resampled_ivars[index] = resampled_ivar
            pb.update()
                
    return resampled_fluxs, resampled_ivars


    # save to new file

if __name__ == "__main__":

    from astropy.table import Table
    from tqdm import tqdm

    resampled_flux, resampled_ivar = shift_and_resample_to_rest_frame(
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_07_21/outdir_wu_K/apMADGICS_out_x_starLines_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_07_21/outdir_wu_K/apMADGICS_out_x_starLines_err_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_07_21/outdir_wu_K/apMADGICS_out_RV_pixoff_final.h5"
    )    

    # Clip off the first 125 pixels in order to match the apStar/FERRE sampling
    si = 125
    import os
    resampled_flux = resampled_flux[:, si:]
    resampled_ivar = resampled_ivar[:, si:]
    from astropy.io import fits
    output_dir = "/uufs/chpc.utah.edu/common/home/sdss50/sdsswork/users/u6020307/apMADGICS_20230721_Konventional/"
    os.makedirs(output_dir, exist_ok=True)

    N, P = resampled_flux.shape
    for i in range(N):
        Table(data=dict(flux=resampled_flux[i], ivar=resampled_ivar[i])).write(f"{output_dir}/apMADGICS-20230721-{i}.fits", overwrite=True)

    '''
    from astropy.table import Table
    from tqdm import tqdm

    resampled_flux, resampled_ivar = shift_and_resample_to_rest_frame(
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_07_21/outdir_wu/apMADGICS_out_x_starLines_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_07_21/outdir_wu/apMADGICS_out_x_starLines_err_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_07_21/outdir_wu/apMADGICS_out_RV_pixoff_final.h5"
    )    

    # Clip off the first 125 pixels in order to match the apStar/FERRE sampling
    si = 125
    import os
    resampled_flux = resampled_flux[:, si:]
    resampled_ivar = resampled_ivar[:, si:]
    from astropy.io import fits
    output_dir = "/uufs/chpc.utah.edu/common/home/sdss50/sdsswork/users/u6020307/apMADGICS_20230721/"
    os.makedirs(output_dir, exist_ok=True)

    N, P = resampled_flux.shape
    for i in range(N):
        Table(data=dict(flux=resampled_flux[i], ivar=resampled_ivar[i])).write(f"{output_dir}/apMADGICS-20230721-{i}.fits", overwrite=True)
    '''

    '''
    from astropy.table import Table
    from tqdm import tqdm

    resampled_flux, resampled_ivar = shift_and_resample_to_rest_frame(
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_07_20/outdir_wu_injectStellarParams/apMADGICS_out_x_starLines_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_07_20/outdir_wu_injectStellarParams/apMADGICS_out_x_starLines_err_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_07_20/outdir_wu_injectStellarParams/apMADGICS_out_RV_pixoff_final.h5"
    )    

    # Clip off the first 125 pixels in order to match the apStar/FERRE sampling
    si = 125
    import os
    resampled_flux = resampled_flux[:, si:]
    resampled_ivar = resampled_ivar[:, si:]
    from astropy.io import fits
    output_dir = "/uufs/chpc.utah.edu/common/home/sdss50/sdsswork/users/u6020307/apMADGICS_20230720/"
    os.makedirs(output_dir, exist_ok=True)

    N, P = resampled_flux.shape
    for i in range(N):
        Table(data=dict(flux=resampled_flux[i], ivar=resampled_ivar[i])).write(f"{output_dir}/apMADGICS-20230720-{i}.fits", overwrite=True)
    '''

    '''
    from astropy.table import Table
    from tqdm import tqdm

    resampled_flux, resampled_ivar = shift_and_resample_to_rest_frame(
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_07_13/outdir_wu/apMADGICS_out_x_starLines_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_07_13/outdir_wu/apMADGICS_out_x_starLines_err_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_07_13/outdir_wu/apMADGICS_out_RV_pixoff_final.h5"
    )    

    # Clip off the first 125 pixels in order to match the apStar/FERRE sampling
    si = 125
    import os
    resampled_flux = resampled_flux[:, si:]
    resampled_ivar = resampled_ivar[:, si:]
    from astropy.io import fits
    output_dir = "/uufs/chpc.utah.edu/common/home/sdss50/sdsswork/users/u6020307/apMADGICS_20230713/"
    os.makedirs(output_dir, exist_ok=True)

    N, P = resampled_flux.shape
    for i in range(N):
        Table(data=dict(flux=resampled_flux[i], ivar=resampled_ivar[i])).write(f"{output_dir}/apMADGICS-20230713-{i}.fits", overwrite=True)
    '''
    '''

    from astropy.table import Table
    from tqdm import tqdm

    resampled_flux, resampled_ivar = shift_and_resample_to_rest_frame(
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_07_12/outdir_wu/apMADGICS_out_x_starLines_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_07_12/outdir_wu/apMADGICS_out_x_starLines_err_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_07_12/outdir_wu/apMADGICS_out_RV_pixoff_final.h5"
    )    

    # Clip off the first 125 pixels in order to match the apStar/FERRE sampling
    si = 125
    import os
    resampled_flux = resampled_flux[:, si:]
    resampled_ivar = resampled_ivar[:, si:]
    from astropy.io import fits
    output_dir = "/uufs/chpc.utah.edu/common/home/sdss50/sdsswork/users/u6020307/apMADGICS_20230712/"
    os.makedirs(output_dir, exist_ok=True)

    N, P = resampled_flux.shape
    for i in range(N):
        Table(data=dict(flux=resampled_flux[i], ivar=resampled_ivar[i])).write(f"{output_dir}/apMADGICS-20230712-{i}.fits", overwrite=True)
    '''


    '''
    from astropy.table import Table
    from tqdm import tqdm

    resampled_flux, resampled_ivar = shift_and_resample_to_rest_frame(
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_07_06/outdir_wu/apMADGICS_out_x_starLines_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_07_06/outdir_wu/apMADGICS_out_x_starLines_err_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_07_06/outdir_wu/apMADGICS_out_RV_pixoff_final.h5"
    )    

    # Clip off the first 125 pixels in order to match the apStar/FERRE sampling
    si = 125
    import os
    resampled_flux = resampled_flux[:, si:]
    resampled_ivar = resampled_ivar[:, si:]
    from astropy.io import fits
    output_dir = "/uufs/chpc.utah.edu/common/home/sdss50/sdsswork/users/u6020307/apMADGICS_20230706/"
    os.makedirs(output_dir, exist_ok=True)

    N, P = resampled_flux.shape
    for i in range(N):
        Table(data=dict(flux=resampled_flux[i], ivar=resampled_ivar[i])).write(f"{output_dir}/apMADGICS-20230706-{i}.fits", overwrite=True)
    '''

    '''

    from astropy.table import Table
    from tqdm import tqdm

    meta = Table.read(
        "/uufs/chpc.utah.edu/common/home/sdss50/sdsswork/users/u6039752/working/2023_03_24/input_list.txt",
        names=("index", "telescope", "field", "plate", "mjd", "basename", "plate_path", "fiber_index"),
        format="ascii"
    )
    resampled_flux, resampled_ivar = shift_and_resample_to_rest_frame(
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_06_25/outdir_wu/apMADGICS_out_x_starLines_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_06_25/outdir_wu/apMADGICS_out_x_starLines_err_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_06_25/outdir_wu/apMADGICS_out_RV_pixoff_final.h5"
    )    

    # Clip off the first 125 pixels in order to match the apStar/FERRE sampling
    si = 125
    import os
    resampled_flux = resampled_flux[:, si:]
    resampled_ivar = resampled_ivar[:, si:]
    from astropy.io import fits
    output_dir = "/uufs/chpc.utah.edu/common/home/sdss50/sdsswork/users/u6020307/apMADGICS_20230625/"
    os.makedirs(output_dir, exist_ok=True)

    meta["fiber"] = [6] * len(meta)
    for i, row in enumerate(tqdm(meta)):
        Table(data=dict(flux=resampled_flux[i], ivar=resampled_ivar[i])).write(f"{output_dir}/apMADGICS-20230625-dr17-{row['telescope']}-{row['field']}-{row['plate']}-{row['mjd']}-{row['fiber']:0>3.0f}.fits", overwrite=True)
    '''
        

    '''
    from astropy.table import Table
    from tqdm import tqdm

    meta = Table.read(
        "/uufs/chpc.utah.edu/common/home/sdss50/sdsswork/users/u6039752/working/2023_03_24/input_list.txt",
        names=("index", "telescope", "field", "plate", "mjd", "basename", "plate_path", "fiber_index"),
        format="ascii"
    )
    resampled_flux, resampled_ivar = shift_and_resample_to_rest_frame(
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_06_20/outdir_wu/apMADGICS_out_x_starLines_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_06_20/outdir_wu/apMADGICS_out_x_starLines_err_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_06_20/outdir_wu/apMADGICS_out_RV_pixoff_final.h5"
    )    

    # Clip off the first 125 pixels in order to match the apStar/FERRE sampling
    si = 125
    import os
    resampled_flux = resampled_flux[:, si:]
    resampled_ivar = resampled_ivar[:, si:]
    from astropy.io import fits
    output_dir = "/uufs/chpc.utah.edu/common/home/sdss50/sdsswork/users/u6020307/apMADGICS_20230620/"
    os.makedirs(output_dir, exist_ok=True)

    meta["fiber"] = [6] * len(meta)
    for i, row in enumerate(tqdm(meta)):
        Table(data=dict(flux=resampled_flux[i], ivar=resampled_ivar[i])).write(f"{output_dir}/apMADGICS-20230620-dr17-{row['telescope']}-{row['field']}-{row['plate']}-{row['mjd']}-{row['fiber']:0>3.0f}.fits", overwrite=True)
    '''

    '''
    from astropy.table import Table
    from tqdm import tqdm

    meta = Table.read(
        "/uufs/chpc.utah.edu/common/home/sdss50/sdsswork/users/u6039752/working/2023_03_24/input_list.txt",
        names=("index", "telescope", "field", "plate", "mjd", "basename", "plate_path", "fiber_index"),
        format="ascii"
    )
    
    resampled_flux, resampled_ivar = shift_and_resample_to_rest_frame(
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_06_18/outdir_wu/apMADGICS_out_x_starLines_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_06_18/outdir_wu/apMADGICS_out_x_starLines_err_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_06_18/outdir_wu/apMADGICS_out_RV_pixoff_final.h5"
    )    

    # Clip off the first 125 pixels in order to match the apStar/FERRE sampling
    si = 125
    import os
    resampled_flux = resampled_flux[:, si:]
    resampled_ivar = resampled_ivar[:, si:]
    from astropy.io import fits
    output_dir = "/uufs/chpc.utah.edu/common/home/sdss50/sdsswork/users/u6020307/apMADGICS_20230618_stddev/"
    os.makedirs(output_dir, exist_ok=True)

    meta["fiber"] = [6] * len(meta)
    for i, row in enumerate(tqdm(meta)):
        Table(data=dict(flux=resampled_flux[i], ivar=resampled_ivar[i])).write(f"{output_dir}/apMADGICS-20230618-stddev-dr17-{row['telescope']}-{row['field']}-{row['plate']}-{row['mjd']}-{row['fiber']:0>3.0f}.fits", overwrite=True)
    '''


    '''
    from astropy.table import Table
    from tqdm import tqdm

    meta = Table.read(
        "/uufs/chpc.utah.edu/common/home/sdss50/sdsswork/users/u6039752/working/2023_03_24/input_list.txt",
        names=("index", "telescope", "field", "plate", "mjd", "basename", "plate_path", "fiber_index"),
        format="ascii"
    )
    def shift_and_resample_to_rest_frame(flux_path, flux_var_path, rv_pixoff_path, n_res=4.25):
        import os
        flux_fp = h5py.File(flux_path, "r")
        flux_err_fp = h5py.File(flux_var_path, "r")
        rv_pixoff_fp = h5py.File(rv_pixoff_path, "r")
        get_key = lambda x: os.path.basename(x).split(".")[0][14:] 

        v_rads = rv_pixoff_fp[get_key(rv_pixoff_path)][:]
        fluxs = 1 + flux_fp[get_key(flux_path)][:]
        flux_vars = flux_err_fp[get_key(flux_var_path)][:]

        N, P = fluxs.shape
        
        executor = concurrent.futures.ProcessPoolExecutor(4)

        all_args = [(i, v_rad, flux, flux_var, n_res) for i, (v_rad, flux, flux_var) in enumerate(zip(v_rads, fluxs, flux_vars))]
        futures = [executor.submit(_shift_and_resample_to_rest_frame, *args) for args in all_args]

        resampled_fluxs = np.zeros((N, P), dtype=float)
        resampled_ivars = np.zeros((N, P), dtype=float)

        with tqdm(total=N, desc="Resampling in parallel") as pb:
            for future in concurrent.futures.as_completed(futures):
                index, resampled_flux, resampled_ivar = future.result()
                resampled_fluxs[index] = resampled_flux
                resampled_ivars[index] = resampled_ivar
                pb.update()
                
        
        return resampled_fluxs, resampled_ivars


    resampled_flux, resampled_ivar = shift_and_resample_to_rest_frame(
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_06_18/outdir_wu/apMADGICS_out_x_starLines_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_06_18/outdir_wu/apMADGICS_out_fluxerr2.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_06_18/outdir_wu/apMADGICS_out_RV_pixoff_final.h5"
    )    

    # Clip off the first 125 pixels in order to match the apStar/FERRE sampling
    si = 125
    import os
    resampled_flux = resampled_flux[:, si:]
    resampled_ivar = resampled_ivar[:, si:]
    from astropy.io import fits
    output_dir = "/uufs/chpc.utah.edu/common/home/sdss50/sdsswork/users/u6020307/apMADGICS_20230618_fluxvar/"
    os.makedirs(output_dir, exist_ok=True)

    meta["fiber"] = [6] * len(meta)
    for i, row in enumerate(tqdm(meta)):
        Table(data=dict(flux=resampled_flux[i], ivar=resampled_ivar[i])).write(f"{output_dir}/aapMADGICS-20230618-fluxvar-dr17-{row['telescope']}-{row['field']}-{row['plate']}-{row['mjd']}-{row['fiber']:0>3.0f}.fits", overwrite=True)
    
    '''


    '''
    from astropy.table import Table
    from tqdm import tqdm

    meta = Table.read(
        "/uufs/chpc.utah.edu/common/home/sdss50/sdsswork/users/u6039752/working/2023_03_24/input_list.txt",
        names=("index", "telescope", "field", "plate", "mjd", "basename", "plate_path", "fiber_index"),
        format="ascii"
    )

    resampled_flux, resampled_ivar = shift_and_resample_to_rest_frame(
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_06_04/outdir_wu_50_295only/apMADGICS_out_x_starLines_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_06_04/outdir_wu_50_295only/apMADGICS_out_x_starLines_err_v0.h5",
        "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_06_04/outdir_wu_50_295only/apMADGICS_out_RV_pixoff_final.h5"
    )
    
    # Clip off the first 125 pixels in order to match the apStar/FERRE sampling
    si = 125
    resampled_flux = resampled_flux[:, si:]
    resampled_ivar = resampled_ivar[:, si:]

    import os
    from astropy.io import fits
    output_dir = "/uufs/chpc.utah.edu/common/home/sdss50/sdsswork/users/u6020307/apMADGICS_2023_06_04_wu_50_indexbugfixed/"
    os.makedirs(output_dir, exist_ok=True)

    meta["fiber"] = [6] * len(meta)
    for i, row in enumerate(tqdm(meta)):
        Table(data=dict(flux=resampled_flux[i], ivar=resampled_ivar[i])).write(f"{output_dir}/apMADGICS-2023_06_04-wu_50-dr17-{row['telescope']}-{row['field']}-{row['plate']}-{row['mjd']}-{row['fiber']:0>3.0f}.fits", overwrite=True)
    '''


    '''
    from astropy.table import Table
    from tqdm import tqdm

    meta = Table.read(
        "/uufs/chpc.utah.edu/common/home/sdss50/sdsswork/users/u6039752/working/2023_03_24/input_list.txt",
        names=("index", "telescope", "field", "plate", "mjd", "basename", "plate_path", "fiber_index"),
        format="ascii"
    )

    dir = "/uufs/chpc.utah.edu/common/home/u6039752/scratch1/working/2023_06_18/outdir_wu"
    

    def shift_and_resample_to_rest_frame(flux_path, flux_err_path, rv_pixoff_path, n_res=4.25):
        
        flux_fp = h5py.File(flux_path, "r")
        flux_err_fp = h5py.File(flux_err_path, "r")
        rv_pixoff_fp = h5py.File(rv_pixoff_path, "r")

        v_rads = rv_pixoff_fp["RV_pixoff_final"][:]
        fluxs = 1 + flux_fp["x_starLines_v0"][:, 125:]
        flux_vars = flux_err_fp["apMADGICS_out_fluxerr2"][:, 25:]**2

        raise a
        N, P = fluxs.shape
        


        executor = concurrent.futures.ProcessPoolExecutor(4)

        all_args = [(i, v_rad, flux, flux_var, n_res) for i, (v_rad, flux, flux_var) in enumerate(zip(v_rads, fluxs, flux_vars))]
        futures = [executor.submit(_shift_and_resample_to_rest_frame, *args) for args in all_args]

        resampled_fluxs = np.zeros((N, P), dtype=float)
        resampled_ivars = np.zeros((N, P), dtype=float)

        with tqdm(total=N, desc="Resampling in parallel") as pb:
            for future in concurrent.futures.as_completed(futures):
                index, resampled_flux, resampled_ivar = future.result()
                resampled_fluxs[index] = resampled_flux
                resampled_ivars[index] = resampled_ivar
                pb.update()
                
        
        return resampled_fluxs, resampled_ivars
        

    resampled_flux, resampled_ivar = shift_and_resample_to_rest_frame(
        f"{dir}/apMADGICS_out_x_starLines_v0.h5",
        f"{dir}/apMADGICS_out_fluxerr2.h5",
        f"{dir}/apMADGICS_out_RV_pixoff_final.h5"
    )
    

    import os
    from astropy.io import fits
    output_dir = "/uufs/chpc.utah.edu/common/home/sdss50/sdsswork/users/u6020307/apMADGICS/"
    os.makedirs(output_dir, exist_ok=True)

    meta["fiber"] = [6] * len(meta)
    for i, row in enumerate(tqdm(meta)):
        Table(data=dict(flux=resampled_flux[i], ivar=resampled_ivar[i])).write(f"{output_dir}/apMADGICS-2023_06_04-wu_50-dr17-{row['telescope']}-{row['field']}-{row['plate']}-{row['mjd']}-{row['fiber']:0>3.0f}.fits", overwrite=True)
    '''