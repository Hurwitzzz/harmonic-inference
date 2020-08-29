from typing import List, Iterable, Union, Tuple
from pathlib import Path
import logging

from tqdm import tqdm
import numpy as np
import pandas as pd
import h5py
from torch.utils.data import Dataset

from harmonic_inference.data.piece import Piece, ScorePiece
import harmonic_inference.utils.harmonic_utils as hu


class HarmonicDataset(Dataset):
    def __init__(self):
        self.padded = False
        self.h5_path = None

    def __len__(self):
        if self.h5_path:
            with h5py.File(self.h5_path, 'r') as h5_file:
                length = len(h5_file['inputs'])
            return length
        return len(self.inputs)

    def __getitem__(self, item):
        data = {}

        if self.h5_path:
            with h5py.File(self.h5_path, 'r') as h5_file:
                data["inputs"] = (
                    h5_file["inputs"][item, :h5_file['input_lengths'][item]]
                    if 'input_lengths' in h5_file
                    else h5_file["inputs"][item]
                )
                data["targets"] = (
                    h5_file["targets"][item, :h5_file['target_lengths'][item]]
                    if 'target_lengths' in h5_file
                    else h5_file["targets"][item]
                )
        else:
            data["inputs"] = (
                self.inputs[item, :self.input_lengths[item]]
                if hasattr(self, 'input_lengths')
                else self.inputs[item]
            )
            data["targets"] = (
                self.targets[item, :self.target_lengths[item]]
                if hasattr(self, 'target_lengths')
                else self.targets[item]
            )
        return data

    def pad(self):
        """
        Default padding function to pad a HarmonicDataset's input and target arrays to be of the
        same size, so that they can be combined into a numpy nd-array, one element per row
        (with 0's padded to the end).

        This function works if input and target are lists of np.ndarrays, and the ndarrays match
        in every dimension except possibly the first.

        This also adds fields input_lengths and target_lengths (both arrays, with 1 integer per
        input and target), representing the lengths of the non-padded entries for each piece.

        Finally, this sets self.padded to True.
        """
        self.targets, self.target_lengths = pad_array(self.targets)
        self.inputs, self.input_lengths = pad_array(self.inputs)
        self.padded = True

    def to_h5(self, h5_path: Union[str, Path]):
        """
        Write this HarmonicDataset out to an h5 file, containing its inputs and targets.

        Parameters
        ----------
        h5_path : Union[str, Path]
            The filename of the h5 file to write to.
        """
        if isinstance(h5_path, str):
            h5_path = Path(h5_path)

        if not h5_path.parent.exists():
            h5_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.padded:
            self.pad()

        h5_file = h5py.File(h5_path, 'w')
        h5_file.create_dataset('inputs', data=self.inputs, compression="gzip")
        h5_file.create_dataset('targets', data=self.targets, compression="gzip")
        if hasattr(self, 'input_lengths'):
            h5_file.create_dataset('input_lengths', data=self.input_lengths, compression="gzip")
        if hasattr(self, 'target_lengths'):
            h5_file.create_dataset('target_lengths', data=self.target_lengths, compression="gzip")
        h5_file.close()


class ChordTransitionDataset(HarmonicDataset):
    def __init__(self, pieces: List[Piece]):
        super().__init__()
        self.targets = [piece.get_chord_change_indices() for piece in pieces]
        self.inputs = [
            np.vstack([note.to_vec() for note in piece.get_inputs()]) for piece in pieces
        ]


class ChordClassificationDataset(HarmonicDataset):
    def __init__(self, pieces: List[Piece]):
        super().__init__()
        self.targets = np.array([
            hu.get_chord_one_hot_index(
                chord.chord_type,
                chord.root,
                chord.pitch_type,
                inversion=chord.inversion,
                use_inversion=True,
            )
            for piece in pieces
            for chord in piece.get_chords()
        ])
        self.inputs = []
        for piece in pieces:
            self.inputs.extend(piece.get_chord_note_inputs(window=2))

    def pad(self):
        self.inputs, self.input_lengths = pad_array(self.inputs)


class ChordSequenceDataset(HarmonicDataset):
    pass


class KeyTransitionDataset(HarmonicDataset):
    pass


class KeySequenceDataset(HarmonicDataset):
    pass


def h5_to_dataset(h5_path: Union[str, Path], dataset_class: HarmonicDataset) -> HarmonicDataset:
    """
    Load a harmonic dataset object from an h5 file into the given HarmonicDataset subclass.

    Parameters
    ----------
    h5_path : str or Path
        The h5 file to load the data from.
    dataset_class : HarmonicDataset
        The dataset class to load the data into and return.

    Returns
    -------
    dataset : HarmonicDataset
        A HarmonicDataset of the given class, loaded with inputs and targets from the given
        h5 file.
    """
    dataset = dataset_class([])

    with h5py.File(h5_path, 'r') as h5_file:
        assert 'inputs' in h5_file
        assert 'targets' in h5_file
        dataset.padded = True
        dataset.h5_path = h5_path

    return dataset


def pad_array(array: List[np.array]) -> Tuple[np.array, np.array]:
    """
    Pad the given list, whose elements must only match in dimensions past the first, into a
    numpy nd-array of equal dimensions.

    Parameters
    ----------
    array : List[np.array]
        A list of numpy ndarrays. The shape of each ndarray must match in every dimension except
        the first.

    Returns
    -------
    padded_array : np.array
        The given list, packed into a numpy nd-array. Since the first dimension of each given
        nested numpy array need not be equal, each is padded with zeros to match the longest.
    array_lengths : np.array
        The size of the first dimension of each nested numpy nd-array before padding. Using this,
        the original array[i] can be gotten with padded_array[i, :array_lengths[i]].
    """
    array_lengths = np.array([len(item) for item in array])

    full_array_size = [len(array), max(array_lengths)]
    if len(array[0].shape) > 1:
        full_array_size += list(array[0].shape)[1:]
    full_array_size = tuple(full_array_size)

    padded_array = np.zeros(full_array_size)
    for index, item in enumerate(array):
        padded_array[index, :len(item)] = item

    return padded_array, array_lengths


def get_dataset_splits(
    files: pd.DataFrame,
    measures: pd.DataFrame,
    chords: pd.DataFrame,
    notes: pd.DataFrame,
    datasets: Iterable[HarmonicDataset],
    splits: Iterable[float] = [0.8, 0.1, 0.1],
    seed: int = None,
) -> Iterable[Iterable[HarmonicDataset]]:
    """
    Get datasets representing splits of the data in the given DataFrames.

    Parameters
    ----------
    files : pd.DataFrame
        A DataFrame with data about all of the files in the DataFrames.
    measures : pd.DataFrame
        A DataFrame with information about the measures of the pieces in the data.
    chords : pd.DataFrame
        A DataFrame with information about the chords of the pieces in the data.
    notes : pd.DataFrame
        A DataFrame with information about the notes of the pieces in the data.
    datasets : Iterable[HarmonicDataset]
        An Iterable of HarmonicDataset class objects, each representing a different type of
        HarmonicDataset subclass to make a Dataset from. These are all passed so that they will
        have identical splits.
    splits : Iterable[float]
        An Iterable of floats representing the proportion of pieces which will go into each split.
        This will be normalized to sum to 1.
    seed : int
        A numpy random seed, if given.

    Returns
    -------
    dataset_splits : Iterable[Iterable[HarmonicDataset]]
        An iterable, the length of `dataset` representing the splits for each given dataset type.
        Each element is itself an iterable the length of `splits`.
    """
    assert sum(splits) != 0
    splits = np.array(splits) / sum(splits)

    if seed is not None:
        np.random.seed(seed)

    pieces = []
    df_indexes = []

    for i in tqdm(files.index):
        file_name = f'{files.loc[i].corpus_name}/{files.loc[i].file_name}'
        logging.info(f"Parsing {file_name} (id {i})")

        dfs = [chords, measures, notes]
        names = ['chords', 'measures', 'notes']
        exists = [i in df.index.get_level_values(0) for df in dfs]

        if not all(exists):
            for exist, df, name in zip(exists, dfs, names):
                if not exist:
                    logging.warning(f'{name}_df does not contain {file_name} data (id {i}).')
            continue

        try:
            piece = ScorePiece(notes.loc[i], chords.loc[i], measures.loc[i])
            pieces.append(piece)
            df_indexes.append(i)
        except BaseException as e:
            logging.error(f"Error parsing index {i}: {e}")
            continue

    # Shuffle the pieces and the df_indexes the same way
    shuffled_indexes = np.arange(len(pieces))
    np.random.shuffle(shuffled_indexes)
    pieces = np.array(pieces)[shuffled_indexes]
    df_indexes = np.array(df_indexes)[shuffled_indexes]

    dataset_splits = np.full((len(datasets), len(splits)), None)
    prop = 0
    for split_index, split_prop in enumerate(splits):
        start = int(round(prop * len(pieces)))
        prop += split_prop
        end = int(round(prop * len(pieces)))

        if start == end:
            logging.warning(
                f"Split {split_index} with prop {split_prop} contains no pieces. Returning None "
                "for those."
            )
            continue

        for dataset_index, dataset_class in enumerate(datasets):
            dataset_splits[dataset_index][split_index] = dataset_class(pieces[start:end])

    return dataset_splits
