import os
import numpy as np
import collections
import librosa
import torch
from torch.utils.data import Dataset

from TTS.utils.text import text_to_sequence
from TTS.utils.audio import AudioProcessor
from TTS.utils.data import prepare_data, pad_data, pad_per_step


class LJSpeechDataset(Dataset):

    def __init__(self, csv_file, root_dir, outputs_per_step, sample_rate,
                text_cleaner, num_mels, min_level_db, frame_shift_ms,
                frame_length_ms, preemphasis, ref_level_db, num_freq, power):
        
        with open(csv_file, "r") as f:
            self.frames = [line.split('|') for line in f]
        self.root_dir = root_dir
        self.outputs_per_step = outputs_per_step
        self.sample_rate = sample_rate
        self.cleaners = text_cleaner
        self.ap = AudioProcessor(sample_rate, num_mels, min_level_db, frame_shift_ms,
                                 frame_length_ms, preemphasis, ref_level_db, num_freq, power)
        print(" > Reading LJSpeech from - {}".format(root_dir))
        print(" | > Number of instances : {}".format(len(self.frames)))
        self._sort_frames()

    def load_wav(self, filename):
        try:
            audio = librosa.core.load(filename, sr=self.sample_rate)
            return audio
        except RuntimeError as e:
            print(" !! Cannot read file : {}".format(filename))

    def _sort_frames(self):
        r"""Sort sequences in ascending order"""
        lengths = np.array([len(ins[1]) for ins in self.frames])
        
        print(" | > Max length sequence {}".format(np.max(lengths)))
        print(" | > Min length sequence {}".format(np.min(lengths)))
        print(" | > Avg length sequence {}".format(np.mean(lengths)))
        
        idxs = np.argsort(lengths)
        new_frames = [None] * len(lengths)
        for i, idx in enumerate(idxs):
            new_frames[i] = self.frames[idx]
        self.frames = new_frames
        
    def __len__(self):
        return len(self.frames)

    def __getitem__(self, idx):
        wav_name = os.path.join(self.root_dir,
                                self.frames[idx][0]) + '.wav'
        text = self.frames[idx][1]
        text = np.asarray(text_to_sequence(text, [self.cleaners]), dtype=np.int32)
        wav = np.asarray(self.load_wav(wav_name)[0], dtype=np.float32)
        sample = {'text': text, 'wav': wav, 'item_idx': self.frames[idx][0]}
        return sample

    def get_dummy_data(self):
        r"""Get a dummy input for testing"""
        return torch.autograd.Variable(torch.ones(16, 143)).type(torch.LongTensor)

    def collate_fn(self, batch):
        r"""
            Perform preprocessing and create a final data batch:
            1. PAD sequences with the longest sequence in the batch
            2. Convert Audio signal to Spectrograms.
            3. PAD sequences that can be divided by r.
            4. Convert Numpy to Torch tensors.
        """

        # Puts each data field into a tensor with outer dimension batch size
        if isinstance(batch[0], collections.Mapping):
            keys = list()

            wav = [d['wav'] for d in batch]
            item_idxs = [d['item_idx'] for d in batch]
            text = [d['text'] for d in batch]

            text_lenghts = np.array([len(x) for x in text])
            max_text_len = np.max(text_lenghts)

            # PAD sequences with largest length of the batch
            text = prepare_data(text).astype(np.int32)
            wav = prepare_data(wav)

            linear = np.array([self.ap.spectrogram(w).astype('float32') for w in wav])
            mel = np.array([self.ap.melspectrogram(w).astype('float32') for w in wav])
            assert mel.shape[2] == linear.shape[2]
            timesteps = mel.shape[2]

            # PAD with zeros that can be divided by outputs per step
            if (timesteps + 1) % self.outputs_per_step != 0:
                pad_len = self.outputs_per_step - \
                        ((timesteps + 1) % self.outputs_per_step)
                pad_len += 1
            else:
                pad_len = 1
            linear = pad_per_step(linear, pad_len)
            mel = pad_per_step(mel, pad_len)

            # reshape jombo
            linear = linear.transpose(0, 2, 1)
            mel = mel.transpose(0, 2, 1)

            # convert things to pytorch
            text_lenghts = torch.LongTensor(text_lenghts)
            text = torch.LongTensor(text)
            linear = torch.FloatTensor(linear)
            mel = torch.FloatTensor(mel)
            return text, text_lenghts, linear, mel, item_idxs[0]

        raise TypeError(("batch must contain tensors, numbers, dicts or lists;\
                         found {}"
                         .format(type(batch[0]))))
