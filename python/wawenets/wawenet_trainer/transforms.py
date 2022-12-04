import torch

from skimage.exposure import rescale_intensity

# put pytorch-style transforms here


def normalize_target(target, input_min, input_max, target_min=-1, target_max=1):
    """converts a target value with known range to equivalent value in
    [-1, 1]"""
    old_range = input_max - input_min
    target_range = target_max - target_min
    return (((target - input_min) * target_range) / old_range) + target_min


def denormalize_target(
    normalized_target, target_min, target_max, input_min=-1, input_max=1
):
    """converts a normalized target to the equivalent value in
    [target_min, target_max]"""
    old_range = input_max - input_min
    target_range = target_max - target_min
    return (((normalized_target - input_min) * target_range) / old_range) + target_min


class NormalizeTarget:
    def __init__(self, norm_ind):
        self.norm_ind = norm_ind

    def __call__(self, sample):
        sample["pred_metric"][self.norm_ind] = self.normalizer(
            sample["pred_metric"][self.norm_ind],
            self.norm_arg_2,
            self.norm_arg_3,
        )
        return sample

    def norm(self, column_vec):
        """accepts a column vector of un-normalized data, returns a column
        vector of normalized data"""
        return self.normalizer(column_vec, self.norm_arg_2, self.norm_arg_3)

    def denorm(self, column_vec):
        """accepts a column vector of normalized data, returns a column
        vector of denormalized data"""
        return self.denormalizer(column_vec, self.norm_arg_2, self.norm_arg_3)


class NormalizeNISQA(NormalizeTarget):
    """normalize NISQA data to the range (-1, 1)."""

    MIN = 1
    MAX = 5
    name = "¯\\_(ツ)_/¯"

    def __init__(self, norm_ind=0):
        super().__init__(norm_ind)
        self.normalizer = normalize_target
        self.denormalizer = denormalize_target
        self.norm_arg_2 = self.MIN
        self.norm_arg_3 = self.MAX


class NormalizeNISQAmos(NormalizeNISQA):
    """normalize NISQA MOS values to the range (-1, 1)."""

    name = "MOS"


class NormalizeNISQAnoi(NormalizeNISQA):
    """normalize NISQA noise values to the range (-1, 1)."""

    name = "NOI"


class NormalizeNISQAcol(NormalizeNISQA):
    """normalize NISQA color values to the range (-1, 1)."""

    name = "COL"


class NormalizeNISQAdis(NormalizeNISQA):
    """normalize NISQA discontinuity values to the range (-1, 1)."""

    name = "DIS"


class NormalizeNISQAloud(NormalizeNISQA):
    """normalize NISQA loudness values to the range (-1, 1)."""

    name = "LOUD"


class NormalizeNISQAPESQMOSLQO(NormalizeNISQA):
    """normalize PESQMOSLQO values to the range (-1, 1)."""

    name = "PESQMOSLQO"
    MIN = 1.01
    MAX = 4.64


class NormalizeNISQAPOLQAMOSLQO(NormalizeNISQA):
    """normalize POLQAMOSLQO values to the range (-1, 1)."""

    name = "POLQAMOSLQO"
    MIN = 1
    MAX = 4.75


class NormalizeNISQAPEMO(NormalizeNISQA):
    """normalize PEMO values to the range (-1, 1)."""

    name = "PEMO"
    MIN = 0
    MAX = 1


class NormalizeNISQAViSQOL3_C310(NormalizeNISQA):
    """normalize ViSQOL3_C310 values to the range (-1, 1)."""

    name = "ViSQOL3_C310"
    MIN = 1
    MAX = 5


class NormalizeNISQASTOI(NormalizeNISQA):
    """normalize STOI values to the range (-1, 1)."""

    name = "STOI"
    MIN = 0.45
    MAX = 1


class NormalizeNISQAESTOI(NormalizeNISQA):
    """normalize ESTOI values to the range (-1, 1)."""

    name = "ESTOI"
    MIN = 0.23
    MAX = 1


class NormalizeNISQASIIBGauss(NormalizeNISQA):
    """normalize SIIBGauss values to the range (-1, 1)."""

    name = "SIIBGauss"
    MIN = 0
    MAX = 750


class NormalizeIUScaledMOS(NormalizeNISQA):
    """normalize IU-style MOS to the range ()"""

    name = "scaled_mos"
    MIN = 0
    MAX = 10


class NormalizeIUMOS(NormalizeNISQA):
    """normalize IU-style MOS to the range ()"""

    name = "mos"
    MIN = 0
    MAX = 100


class RightPadSampleTensor:
    """zero-pad a segment to a specified length"""

    def __init__(self, final_length):
        self.final_length = final_length

    def __call__(self, sample):
        # calculate how much to pad
        num_channels, num_samples = sample["sample_data"].shape
        pad_length = self.final_length - num_samples
        if pad_length == 0:
            return sample
        elif pad_length < 0:
            sample["sample_data"] = sample["sample_data"][:, : self.final_length]
            return sample
        padder = torch.nn.ConstantPad1d((0, pad_length), 0)
        sample["sample_data"] = padder(sample["sample_data"])
        return sample


class AudioToTensor(object):
    """Convert ndarrays in sample to Tensors."""

    def __call__(self, sample):
        sample.update(
            {
                "sample_data": torch.from_numpy(sample["sample_data"]),
                "pred_metric": torch.from_numpy(sample["pred_metric"]),
            }
        )
        return sample


class NormalizeAudio(object):
    """Normalize numpy audio arrays to the range (0, 1)."""

    def __call__(self, sample):
        sample["sample_data"] = rescale_intensity(
            sample["sample_data"],
            in_range=(-(2**15) + 1, 2**15 - 1),
            out_range=(-1, 1),
        )
        return sample


class InvertAudioPhase(object):
    """Invert the phase of an audio vector for data augmentation purposes."""

    def __call__(self, sample):
        sample["sample_data"] = sample["sample_data"] * -1
        return sample
