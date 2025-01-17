from peewee import AutoField
from astra.utils import log
from astra.models.base import BaseModel
from astra.models.fields import BitField
from functools import cached_property
import warnings
import numpy as np



class SpectrumMixin(object):

    def plot(self, rectified=False, plot_model=False, figsize=(8, 3), ylim_percentile=(1, 99)):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")

            import matplotlib.pyplot as plt        
            # to gracefully handle apVisits
            x = np.atleast_2d(self.wavelength)
            y = np.atleast_2d(self.flux) 
            try:
                y_err = np.atleast_2d(self.e_flux)
            except:
                    try:
                        y_err = np.atleast_2d(self.ivar)**-0.5
                    except:
                        y_err = np.nan * np.ones_like(self.flux)
            
            continuum, is_rectified = (1, False)
            if rectified:            
                try:
                    for key in ("continuum", "nmf_continuum"):
                        continuum = getattr(self, key, None)
                        if continuum is not None:
                            is_rectified = True
                            break
                    else:
                        log.warning(f"Cannot find continuum for spectrum {self}")
                        continuum = 1
                except:
                    log.exception(f"Exception when trying to get continum for spectrum {self}")

            has_model_flux = False
            if plot_model:            
                try:
                    for key in ("model_flux", "nmf_model_flux"):
                        model_flux = getattr(self, key, None)
                        if model_flux is not None:
                            has_model_flux = True
                            break
                    else:
                        log.warning(f"No model flux found for spectrum {self}")
                except:
                    log.exception(f"Exception when trying to get model flux for spectrum {self}")

            N, P = y.shape
            
            fig, ax = plt.subplots(figsize=figsize)
            for i in range(N):
                label = None
                if i == 0:
                    try:
                        for k in ("spectrum_pk", "pk", "task_pk"):
                            v = getattr(self, k, None)
                            if v is not None:
                                label = f"{k}={v}"
                    except:
                        None
                            
                ax.plot(
                    x[i],
                    y[i] / continuum,
                    c='k',
                    label=label,
                    drawstyle="steps-mid"
                )
                ax.fill_between(
                    x[i],
                    (y[i] - y_err[i])/continuum,
                    (y[i] + y_err[i])/continuum,
                    step="mid",
                    facecolor="#cccccc",
                    zorder=-1                
                )
            
            if has_model_flux:
                try:
                    ax.plot(
                        self.wavelength,
                        model_flux / continuum,
                        c="tab:red"
                    )
                except:
                    log.exception(f"Exception when trying to plot model flux for {self}")
            
            # discern some useful limits
            ax.set_xlim(*x.flatten()[[0, -1]])
            if is_rectified:
                ax.set_ylim(0, 1.2)
            else:        
                
                ylim = np.clip(np.nanpercentile(y, ylim_percentile), 0, np.inf)
                offset = np.ptp(ylim) * 0.10
                ylim = (ylim[0] - offset, ylim[1] + offset)
                ax.set_ylim(ylim)
            ax.set_xlabel(r"$\lambda$ $(\mathrm{\AA})$")
            ax.set_ylabel(r"$f_\lambda$ $(10^{-17}\,\mathrm{erg}\,\mathrm{s}^{-1}\,\mathrm{cm}^2\,\mathrm{\AA}^{-1})$")
            fig.tight_layout()
            return fig

class Spectrum(BaseModel, SpectrumMixin):

    """ A one dimensional spectrum. """

    pk = AutoField()
    spectrum_type_flags = BitField(default=0)

    def resolve(self):
        for expression, field in self.dependencies():
            if SpectrumMixin not in field.model.__mro__:
                continue
            try:
                q = field.model.select().where(expression)
            except:
                continue
            else:
                if q.exists():
                    return q.first()
                
        raise self.model.DoesNotExist(f"Cannot resolve spectrum with identifier {self.pk}")

    @cached_property
    def ref(self):
        return self.resolve()
    
    def __getattr__(self, attr):
        # Resolve to reference attribute
        return getattr(self.ref, attr)
    
    def __repr__(self):
        return f"<Spectrum pointer -> ({self.ref.__repr__().strip('<>')})>"
    