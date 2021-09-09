
import numpy as np
from collections import OrderedDict

class BitFlagNameMap(object):

    def get_names(self, value):
        names = []
        for k, entry in self.__class__.__dict__.items():
            if k.startswith("_") or k != k.upper(): continue
            
            if isinstance(entry, int):
                v = entry
            else:
                v, comment = entry

            if value & (2**v):
                names.append(k)
        
        return tuple(names)

        

    def get_value(self, *names):
        value = np.int64(0)

        for name in names:
            try:
                entry = getattr(self, name)
            except KeyError:
                raise ValueError(f"no bit flag found named '{name}'")
            
            if isinstance(entry, int):
                entry = (entry, "")
            
            v, comment = entry
            value |= np.int64(2**v)
        
        return value


    def get_level_value(self, level):
        try:
            names = self.levels[level]
        except KeyError:
            raise ValueError(f"No level name '{level}' found (available: {' '.join(list(self.levels.keys()))})")

        return self.get_value(*names)
        


class ParamBitMask(BitFlagNameMap):

    """
    Bitmask class for APOGEE ASPCAP.
    """
    
    GRIDEDGE_BAD = 0, "Parameter within 1/8 grid spacing of grid edge : true value may be off grid"
    CALRANGE_BAD = 1, "Parameter outside valid range of calibration determination"
    OTHER_BAD = 2, "Other error condition"
    FERRE_FAIL = 3, "Failed solution in FERRE"
    PARAM_MISMATCH_BAD = 4, "Elemental abundance from window differs significantly from parameter abundance"
    FERRE_ERR_USED = 5, "FERRE uncertainty used (larger than parametric uncertainty)"
    TEFF_CUT = 6, "Star in region of parameter space where abundances do not appear valid for this element"
    GRIDEDGE_WARN = 8, "Parameter within 1 grid spacing of grid edge (not necessarily bad)"
    CALRANGE_WARN = 9, "Parameter in possibly unreliable range of calibration determination"
    OTHER_WARN = 10, "Other warning condition"
    FERRE_WARN = 11, "FERRE warning (not implemented?)"
    PARAM_MISMATCH_WARN = 12, "Elemental abundance from window differs from parameter abundance"
    OPTICAL_WARN = 13, "Comparison with optical abundances suggests problem"
    ERR_WARN = 14, "Large expected uncertainty or upper limit based on location in parameter space (Teff, [M/H], S/N)"
    FAINT_WARN = 15, "Warning based on faint star/RV combination"
    PARAM_FIXED = 16, "Parameter set at fixed value, not fit"
    RV_WARN = 17, "RV puts important line off of chip"

    levels = OrderedDict([
        [1, ("GRIDEDGE_BAD", "OTHER_BAD", "FERRE_FAIL", "TEFF_CUT")],
    ])


class PixelBitMask(BitFlagNameMap):
    """ Bitmask class for APOGEE pixels """

    BADPIX = 0, "Pixel marked as BAD in bad pixel mask or from strong persistence jump"
    CRPIX = 1, "Pixel marked as cosmic ray in ap3d"
    SATPIX = 2, "Pixel marked as saturated in ap3d"
    UNFIXABLE = 3, "Pixel marked as unfixable in ap3d"
    BADDARK = 4, "Pixel marked as bad as determined from dark frame"
    BADFLAT = 5, "Pixel marked as bad as determined from flat frame"
    BADERR = 6, "Pixel set to have very high error (not used)"
    NOSKY = 7, "No sky available for this pixel from sky fibers"
    LITTROW_GHOST = 8, "Pixel falls in Littrow ghost, may be affected"
    PERSIST_HIGH = 9, "Pixel falls in high persistence region, may be affected"
    PERSIST_MED = 10, "Pixel falls in medium persistence region, may be affected"
    PERSIST_LOW = 11, "Pixel falls in low persistence region, may be affected"
    SIG_SKYLINE = 12, "Pixel falls near sky line that has significant flux compared with object"
    SIG_TELLURIC = 13, "Pixel falls near telluric line that has significant absorption"
    NOT_ENOUGH_PSF = 14, "Less than 50 percent PSF in good pixels"

    FERRE_MASK = 16, "Pixel masked by FERRE mask < 0.001"

    levels = OrderedDict([
        [1, ("BADPIX", "CRPIX", "SATPIX", "UNFIXABLE", "BADDARK", "BADFLAT", "BADERR", "NOSKY", "NOT_ENOUGH_PSF")]
    ])
