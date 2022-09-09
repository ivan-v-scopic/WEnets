import shutil
import tempfile

from pathlib import Path
from typing import Tuple

import torch
import torchaudio

from wawenets.stl_wrapper import LevelMeter, Resampler, SoxConverter, SpeechNormalizer

# handle reading data/etc. here


class RightPadSampleTensor:
    """zero-pad a segment to a specified length"""

    def __init__(self, final_length):
        self.final_length = final_length

    def __call__(self, sample):
        # calculate how much to pad
        num_samples = sample["sample_data"].shape[1]
        pad_length = self.final_length - num_samples
        if pad_length <= 0:
            return sample
        elif pad_length < 0:
            sample["sample_data"] = sample["sample_data"][:, : self.final_length]
            return sample
        padder = torch.nn.ConstantPad1d((0, pad_length), 0)
        # TODO: doublecheck below after all these changes
        sample["sample_data"] = padder(sample["sample_data"]).unsqueeze(0)
        return sample


class WavHandler:
    """handles loading `.wav` files into a tensor suitable for input to WAWEnets

    right now, can only be used as a context manager"""

    def __init__(
        self,
        input_path: Path,
        level_normalization: bool,
        stl_bin_path: str,
        channel: int = 1,
    ) -> None:
        self.input_path = input_path
        self.level_normalization = level_normalization
        self.stl_bin_path = Path(stl_bin_path)
        self.num_input_samples = 48000
        self.samples_per_second = 16000
        self.channel = channel
        # set up all our converters
        self.converter = SoxConverter()
        self.path_to_actlev = self.stl_bin_path / "actlev"
        self.level_meter = LevelMeter(self.path_to_actlev)
        self.path_to_filter = self.stl_bin_path / "filter"
        self.resampler = Resampler(self.path_to_filter)
        self.path_to_sv56 = self.stl_bin_path / "sv56demo"
        self.speech_normalizer = SpeechNormalizer(self.path_to_sv56)
        # set file paths
        self.temp_dir = None
        self.temp_dir_path = None
        self.downmixed_wav = None
        self.input_raw = None
        self.normalized_raw = None
        self.resampled_raw = None
        self.resampled_wav = None
        # wav file metadata
        self.metadata = None
        self.sample_rate = None
        self.duration = None
        self.segment_step_size = None

    def __enter__(self):
        # set up temp dir and intermediate file paths
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_dir_path = Path(self.temp_dir.name)
        self.downmixed_wav = self.temp_dir_path / "downmixed.wav"
        self.input_raw = self.temp_dir_path / "input.raw"
        self.normalized_raw = self.temp_dir_path / "normalized.raw"
        self.resampled_raw = self.temp_dir_path / "resampled.raw"
        self.resampled_wav = self.temp_dir_path / "resampled.wav"

        # store some metadata
        self.metadata = torchaudio.info(self.input_path)
        self.sample_rate = self.metadata.sample_rate
        self.duration = self.metadata.num_frames / self.sample_rate

        # grab the channel we're supposed to be working on
        self.converter.select_channel(self.input_path, self.downmixed_wav, self.channel)

        # convert to raw and resample since just about everything depends on that
        self.converter.wav_to_pcm(self.downmixed_wav, self.input_raw)
        self.resample()
        # jk, don't normalize, convert to raw, or measure here
        # normalize if requested
        # self.normalize_raw()
        # convert to wav
        # self.converter.pcm_to_wav(
        #     self.normalized_raw, self.resampled_wav, self.metadata.sample_rate
        # )

        # now since we've got all the things, do a couple measurements
        # self.active_level, self.speech_activity = self.level_meter.measure(
        #     self.normalized_raw
        # )

        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.temp_dir.cleanup()

    def _copy_file(self, input_path: Path, output_path: Path):
        shutil.copy(input_path, output_path)
        return True

    def resample_raw(self, input_path: Path, output_path: Path, input_sample_rate: int):
        """resamples an input file to 16 kHz. returns true if successful."""
        resampler_map = {
            48000: self.resampler.down_48k_to_16k,
            32000: self.resampler.down_32k_to_16k,
            24000: self.resampler.down_24k_to_16k,
            16000: self._copy_file,  # a little wasteful
            8000: self.resampler.up_8k_to_16k,
        }

        return resampler_map[input_sample_rate](input_path, output_path)

    def resample(self):
        if not self.resample_raw(
            self.input_raw, self.resampled_raw, self.metadata.sample_rate
        ):
            raise RuntimeError(f"unable to resample {self.input_path}")

    def normalize_raw(self, input_raw: Path, normalized_raw: Path):
        """returns a path to the file that should be used after normalization"""
        if self.level_normalization:
            if not self.speech_normalizer.normalizer(input_raw, normalized_raw):
                raise RuntimeError(f"could not normalize {self.resampled_raw}")
        else:
            # if we've been instructed to not normalize, just use the resampled data
            normalized_raw = input_raw
        return normalized_raw

    def load_wav(self, wav_path: Path) -> Tuple[torch.tensor, int]:
        # load to tensor
        audio_data, sample_rate = torchaudio.load(wav_path)

        return audio_data, sample_rate

    def calculate_pad_length(self, num_samples: int) -> int:
        """calculates the number of samples required to facilitate both
        an integer-number of 3-second segments and performing inference on
        all available data."""
        three_second_segs = num_samples // self.num_input_samples
        remainder = num_samples % self.num_input_samples
        if remainder:
            three_second_segs += 1
        return three_second_segs * self.num_input_samples

    def calculate_num_segments(self, num_samples: int, stride: int):
        return ((num_samples - self.num_input_samples) // stride) + 1

    def calculate_start_stop_times(self, num_samples: int, stride: int):
        """generates a list of start and stop times based on the number of samples
        in the file and the specified stride"""
        start = 0
        start_stop_times = list()
        for seg_number in range(self.calculate_num_segments(num_samples, stride)):
            stop = start + self.num_input_samples
            start_stop_times.append(
                (
                    start / self.samples_per_second,
                    stop / self.samples_per_second,
                    seg_number,
                )
            )
            start += stride
        return start_stop_times

    def prepare_segment(self, start_time: float, end_time: float, seg_number: int):
        # we are using sox to trim because otherwise we'd be manually writing
        # samples to disk and doing a bunch of conversions in order to do the
        # measurements/etc.
        trimmed_path = (
            self.resampled_raw.parent
            / f"{self.resampled_raw.stem}_seg_{seg_number}.raw"
        )
        self.converter.trim_pcm(self.resampled_raw, trimmed_path, start_time, end_time)
        normalized_raw = trimmed_path.parent / f"{trimmed_path.stem}_norm.raw"
        normalized_raw = self.normalize_raw(trimmed_path, normalized_raw)
        normalized_wav = normalized_raw.parent / f"{normalized_raw.stem}.wav"
        self.converter.pcm_to_wav(normalized_raw, normalized_wav, 16000)
        active_level, speech_activity = self.level_meter.measure(normalized_raw)
        sample, sample_rate = self.load_wav(normalized_wav)
        pad_length = self.calculate_pad_length(sample.shape[1])
        padder = RightPadSampleTensor(pad_length)

        sample = {"sample_data": sample}
        sample = padder(sample)
        sample["active_level"] = active_level
        sample["speech_activity"] = speech_activity

        return sample

    def prepare_tensor(self, stride) -> torch.tensor:
        """creates a tensor for input to the model. this is where files that are
        longer than three seconds are handled."""

        # TODO: stride, do the right thing
        # for each valid segment, we have to:
        # 1. ask sox to write out the correct portion of a file to a new file
        # 2. normalize that file
        # 3. make measurements
        # 3. convert it to a wav
        # 4. read it
        # 5. pad the last segment if necessary
        # ----- above items can happen in `prepare_segment`
        # 6. pack the segments into a batch (!)

        segments = list()
        active_levels = list()
        speech_activity = list()
        start_stop_times = self.calculate_start_stop_times(
            self.metadata.num_frames, stride
        )
        for seg in start_stop_times:
            segment = self.prepare_segment(*seg)
            segments.append(segment["sample_data"])
            active_levels.append(segment["active_level"])
            speech_activity.append(segment["speech_activity"])

        # TODO: make the batch dimension happen even when the length of
        #       `segments` is only 1
        batch = torch.cat(segments)

        return batch, active_levels, speech_activity, start_stop_times

    def package_metadata(self):
        return {
            "wavfile": self.input_path,
            "channel": self.channel,
            "sample_rate": self.sample_rate,
            "duration": self.duration,
            "level_normalization": self.level_normalization,
        }
