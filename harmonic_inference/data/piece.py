"""A class storing a musical piece from score, midi, or audio format."""
import bisect
from collections import defaultdict
from fractions import Fraction
from typing import Dict, List, Tuple, Union

import numpy as np
import pandas as pd
from tqdm import tqdm

import harmonic_inference.utils.rhythmic_utils as ru
from harmonic_inference.data.chord import Chord
from harmonic_inference.data.data_types import NO_REDUCTION, ChordType, PieceType, PitchType
from harmonic_inference.data.key import Key
from harmonic_inference.data.note import Note


def get_reduction_mask(inputs: List[Union[Chord, Key]], kwargs: Dict = None) -> List[bool]:
    """
    Return a boolean mask that will remove repeated inputs when applied to the given inputs list
    as inputs[mask].

    Parameters
    ----------
    inputs : List[Union[Chord, Key]]
        A List of either Chord or Key objects.
    kwargs : Dict
        A Dictionary of kwargs to pass along to each given input's is_repeated() function.

    Returns
    -------
    mask : List[bool]
        A boolean mask that will remove repeated inputs when applied to the given inputs list
        as inputs = inputs[mask].
    """
    if kwargs is None:
        kwargs = {}

    mask = np.full(len(inputs), True, dtype=bool)

    for prev_index, (prev_obj, next_obj) in enumerate(zip(inputs[:-1], inputs[1:])):
        if next_obj.is_repeated(prev_obj, **kwargs):
            mask[prev_index + 1] = False

    return mask


def get_chord_note_input(
    notes: List[Note],
    measures_df: pd.DataFrame,
    chord_onset: Union[float, Tuple[int, Fraction]],
    chord_offset: Union[float, Tuple[int, Fraction]],
    chord_duration: Union[float, Fraction],
    change_index: int,
    onset_index: int,
    offset_index: int,
    window: int,
    duration_cache: np.array = None,
    chord: Chord = None,
) -> np.array:
    """
    Get an np.array or input vectors relative to a given chord.

    Parameters
    ----------
    notes : List[Note]
        A List of all of the Notes in the Piece.
    measures_df : pd.DataFrame
        The measures_df for this particular Piece.
    chord_onset : Union[float, Tuple[int, Fraction]]
        The onset location of the chord.
    chord_offset : Union[float, Tuple[int, Fraction]]
        The offset location of the chord.
    chord_duration : Union[float, Fraction]
        The duration of the chord.
    change_index : int
        The index of the note matching the onset time of the chord.
    onset_index : int
        The index of the first note of the chord.
    offset_index : int
        The index of the last note of the chord.
    window : int
        The number of notes to pad on each end of the chord's notes. If this goes past the
        bounds of the given notes list, the remaining vectors will contain only 0.
    duration_cache : np.array
        The duration from each note's onset time to the next note's onset time,
        generated by get_duration_cache(...).
    chord : Chord
        The chord the notes belong to, if not None.

    Returns
    -------
    chord_input : np.array
        The input note vectors for this chord.
    """
    # Chord aligns with duration cache
    chord_onset_aligns = chord is None or chord.onset == chord_onset
    chord_offset_aligns = chord is None or chord.offset == chord_offset

    # Add window
    window_onset_index = onset_index - window
    window_offset_index = offset_index + window

    # Shift duration_cache
    dur_from_prevs = [None] + list(duration_cache)
    dur_to_nexts = list(duration_cache)

    # Get the notes within the window
    first_note_index = max(window_onset_index, 0)
    last_note_index = min(window_offset_index, len(notes))
    chord_notes = notes[first_note_index:last_note_index]

    # Get all note vectors within the window
    min_pitch = min([(note.octave, note.pitch_class) for note in chord_notes])
    if duration_cache is None or not chord_onset_aligns:
        note_onsets = np.full(len(chord_notes), None)
    else:
        note_onsets = []
        for note_index in range(first_note_index, last_note_index):
            if note_index < change_index:
                note_onset = -np.sum(duration_cache[note_index:change_index])
            elif note_index > change_index:
                note_onset = np.sum(duration_cache[change_index:note_index])
            else:
                note_onset = Fraction(0)
            note_onsets.append(note_onset)

    note_vectors = np.vstack(
        [
            note.to_vec(
                chord_onset=chord_onset if chord_onset_aligns else chord.onset,
                chord_offset=chord_offset if chord_offset_aligns else chord.offset,
                chord_duration=chord_duration,
                measures_df=measures_df,
                min_pitch=min_pitch,
                note_onset=note_onset,
                dur_from_prev=from_prev,
                dur_to_next=to_next,
            )
            for note, note_onset, from_prev, to_next in zip(
                chord_notes,
                note_onsets,
                dur_from_prevs[first_note_index:last_note_index],
                dur_to_nexts[first_note_index:last_note_index],
            )
        ]
    )

    # Place the note vectors within the final tensor and return
    chord_input = np.zeros((window_offset_index - window_onset_index, note_vectors.shape[1]))
    start = 0 + (first_note_index - window_onset_index)
    end = len(chord_input) - (window_offset_index - last_note_index)
    chord_input[start:end] = note_vectors
    return chord_input


def get_range_start(onset: Union[float, Tuple[int, Fraction]], notes: List[Note]) -> int:
    """
    Get the index of the first note whose offset is after the given range onset.

    Parameters
    ----------
    onset : Union[float, Tuple[int, Fraction]]
        The onset time of a range.
    notes : List[Note]
        A List of the Notes of a piece.

    Returns
    -------
    start : int
        The index of the first note whose offset is after the given range's onset.
    """
    for note_id, note in enumerate(notes):
        if note.onset >= onset or note.offset > onset:
            return note_id

    return len(notes)


class Piece:
    """
    A single musical piece, which can be from score, midi, or audio.
    """

    def __init__(self, data_type: PieceType, name: str = None):
        """
        Create a new musical Piece object of the given data type.

        Parameters
        ----------
        data_type : PieceType
            The data type of the piece.
        name : str
            The name of the piece, an optional identifier.
        """
        self.DATA_TYPE = data_type
        self.name = name

    def get_inputs(self) -> List[Note]:
        """
        Get a list of the inputs for this Piece.

        Returns
        -------
        inputs : np.array
            A List of the inputs for this musical piece.
        """
        raise NotImplementedError

    def get_chord_change_indices(self) -> List[int]:
        """
        Get a List of the indexes (into the input list) at which there are chord changes.

        Returns
        -------
        chord_change_indices : np.array[int]
            The indices (into the inputs list) at which there is a chord change.
        """
        raise NotImplementedError

    def get_chord_ranges(self) -> List[Tuple[int, int]]:
        """
        Get a List of the indexes (into the input list) that contain inputs for each chord.

        Returns
        -------
        ranges : List[Tuple[int, int]]
            The indexes (into the input list) that contain inputs for each chord.
        """
        raise NotImplementedError

    def get_chords(self) -> List[Chord]:
        """
        Get a List of the chords in this piece.

        Returns
        -------
        chords : List[Chord]
            The chords present in this piece. The ith chord occurs for the inputs between
            chord_change_index i (inclusive) and i+1 (exclusive).
        """
        raise NotImplementedError

    def get_chords_within_range(self, start: int = 0, stop: int = None) -> List[Chord]:
        """
        Get a List of the chords in this piece between the given bounds.

        Parameters
        ----------
        start : int
            Return chords starting at this input index. The first chord returned will be
            the chord that is sounding during this input vector.

        stop : int
            Return chords up to this index. The last chord returned will be the chord that is
            sounding during index stop - 1. If None, all chords until the end of the list
            are returned.

        Returns
        -------
        chords : List[Chord]
            The chords present in this piece between the given bounds.
        """
        assert stop is None or stop >= start, "stop must be None or >= start"

        chords = self.get_chords()
        chord_change_indices = self.get_chord_change_indices()

        start_index = bisect.bisect_left(chord_change_indices, start)
        if start_index == len(chord_change_indices) or chord_change_indices[start_index] != start:
            # Subtract 1 to get end of partial chord if exact match is not found
            start_index -= 1

        if stop is None:
            return chords[start_index:]

        end_index = bisect.bisect_left(chord_change_indices, stop, lo=start_index)

        return chords[start_index:end_index]

    def get_chord_note_inputs(
        self,
        window: int = 2,
        ranges: List[Tuple[int, int]] = None,
        change_indices: List[int] = None,
    ) -> np.array:
        """
        Get a list of the note input vectors for each chord in this piece, using an optional
        window on both sides. The ith element in the returned array will be an nd-array of
        size (2 * window + num_notes, note_vector_length).

        Parameters
        ----------
        window : int
            Add this many neighboring notes to each side of each input tensor. Fill with 0s if
            this goes beyond the bounds of all notes.
        ranges : List[Tuple[int, int]]
            A List of chord ranges to use to get the inputs, if not using the ground truth
            chord symbols themselves.
        change_indices : List[int]
            A List of the note whose onset is the onset of each chord range.

        Returns
        -------
        chord_inputs : np.array
            The input note tensor for each chord in this piece.
        """
        raise NotImplementedError

    def get_duration_cache(self) -> List[Fraction]:
        """
        Get a List of the distance from the onset of each input of this Piece to the
        following input. The last value will be the distance from the onset of the last
        input to the offset of the last chord.

        Returns
        -------
        duration_cache : np.array[Fraction]
            A list of the distance from the onset of each input to the onset of the
            following input.
        """
        raise NotImplementedError

    def get_key_change_indices(self) -> List[int]:
        """
        Get a List of the indexes (into the chord list) at which there are key changes.

        Returns
        -------
        key_change_indices : np.array[int]
            The indices (into the chords list) at which there is a key change.
        """
        raise NotImplementedError

    def get_key_change_input_indices(self) -> List[int]:
        """
        Get a List of the indexes (into the input list) at which there are key changes.

        Returns
        -------
        key_change_indices : List[int]
            The indices (into the input list) at which there is a key change.
        """
        chord_changes = self.get_chord_change_indices()
        return [chord_changes[i] for i in self.get_key_change_indices()]

    def get_keys(self) -> List[Key]:
        """
        Get a List of the keys in this piece.

        Returns
        -------
        keys : np.array[Key]
            The keys present in this piece. The ith key occurs for the chords between
            key_change_index i (inclusive) and i+1 (exclusive).
        """
        raise NotImplementedError


class ScorePiece(Piece):
    """
    A single musical piece, in score format.
    """

    def __init__(
        self,
        notes_df: pd.DataFrame,
        chords_df: pd.DataFrame,
        measures_df: pd.DataFrame,
        piece_dict: Dict = None,
        chord_reduction: Dict[ChordType, ChordType] = NO_REDUCTION,
        use_inversions: bool = True,
        use_relative: bool = True,
        name: str = None,
    ):
        """
        Create a ScorePiece object from the given 3 pandas DataFrames.

        Parameters
        ----------
        notes_df : pd.DataFrame
            A DataFrame containing information about the notes contained in the piece.
        chords_df : pd.DataFrame
            A DataFrame containing information about the chords contained in the piece.
        measures_df : pd.DataFrame
            A DataFrame containing information about the measures in the piece.
        piece_dict : Dict
            An optional dict, to load data from instead of calculating everything from the dfs.
            If given, only measures_df must also be given. The rest can be None.
        chord_reduction : Dict[ChordType, ChordType]
            A mapping from every possible ChordType to a reduced ChordType: the type that chord
            should be stored as. This can be used, for example, to store each chord as its triad.
        use_inversions : bool
            True to store inversions in the chord symbols. False to ignore them.
        use_relative : bool
            True to treat relative roots as new local keys. False to treat them as chord symbols
            within the annotated local key.
        name : str
            A string identifier for this piece.
        """
        super().__init__(PieceType.SCORE, name=name)
        self.measures_df = measures_df
        self.duration_cache = None

        if piece_dict is None:
            levels_cache = defaultdict(dict)
            notes = np.array(
                [
                    [note, note_id]
                    for note_id, note in enumerate(
                        notes_df.apply(
                            Note.from_series,
                            axis="columns",
                            measures_df=measures_df,
                            pitch_type=PitchType.TPC,
                            levels_cache=levels_cache,
                        )
                    )
                    if note is not None
                ]
            )
            self.notes, self.note_ilocs = np.hsplit(notes, 2)
            self.notes = np.squeeze(self.notes)
            self.note_ilocs = np.squeeze(self.note_ilocs).astype(int)

            chords = np.array(
                [
                    [chord, chord_id]
                    for chord_id, chord in enumerate(
                        chords_df.apply(
                            Chord.from_series,
                            axis="columns",
                            measures_df=measures_df,
                            pitch_type=PitchType.TPC,
                            levels_cache=levels_cache,
                            reduction=chord_reduction,
                            use_inversion=use_inversions,
                            use_relative=use_relative,
                        )
                    )
                    if chord is not None
                ]
            )
            chords, chord_ilocs = np.hsplit(chords, 2)
            chords = np.squeeze(chords)
            chord_ilocs = np.squeeze(chord_ilocs).astype(int)

            # Remove accidentally repeated chords
            non_repeated_mask = get_reduction_mask(chords, kwargs={"use_inversion": use_inversions})
            self.chords = []
            for chord, mask in zip(chords, non_repeated_mask):
                if mask:
                    self.chords.append(chord)
                else:
                    self.chords[-1].merge_with(chord)
            self.chords = np.array(self.chords)
            self.chord_ilocs = chord_ilocs[non_repeated_mask]

            # The index of the notes where there is a chord change
            self.chord_changes = np.zeros(len(self.chords), dtype=int)
            note_index = 0
            for chord_index, chord in enumerate(self.chords):
                while (
                    note_index + 1 < len(self.notes) and self.notes[note_index].onset < chord.onset
                ):
                    note_index += 1
                self.chord_changes[chord_index] = note_index

            # The note input ranges for each chord
            self.chord_ranges = [
                (get_range_start(chord.onset, self.notes), end)
                for chord, end in zip(self.chords, list(self.chord_changes[1:]) + [len(self.notes)])
            ]

            key_cols = chords_df.loc[
                chords_df.index[self.chord_ilocs],
                [
                    "globalkey",
                    "globalkey_is_minor",
                    "localkey_is_minor",
                    "localkey",
                    "relativeroot",
                ],
            ]
            key_cols = key_cols.fillna("-1")
            changes = key_cols.ne(key_cols.shift()).fillna(True)

            key_changes = np.arange(len(changes))[changes.any(axis=1)]
            keys = np.array(
                [
                    key
                    for key in chords_df.loc[chords_df.index[self.chord_ilocs[key_changes]]].apply(
                        Key.from_series, axis="columns", tonic_type=PitchType.TPC
                    )
                    if key is not None
                ]
            )

            # Remove accidentally repeated keys
            non_repeated_mask = get_reduction_mask(keys, kwargs={"use_relative": use_relative})
            self.keys = keys[non_repeated_mask]
            self.key_changes = key_changes[non_repeated_mask]

        else:
            self.notes = np.array([Note(**note) for note in piece_dict["notes"]])
            self.chords = np.array([Chord(**chord) for chord in piece_dict["chords"]])
            self.keys = np.array([Key(**key) for key in piece_dict["keys"]])
            self.chord_changes = np.array(piece_dict["chord_changes"])
            self.chord_ranges = np.array(piece_dict["chord_ranges"])
            self.key_changes = np.array(piece_dict["key_changes"])

    def get_duration_cache(self):
        if self.duration_cache is None:
            fake_last_note = Note(
                0, 0, self.chords[-1].offset, 0, Fraction(0), (0, Fraction(0)), 0, PitchType.TPC
            )

            self.duration_cache = np.array(
                [
                    ru.get_range_length(prev_note.onset, next_note.onset, self.measures_df)
                    for prev_note, next_note in zip(
                        self.notes, list(self.notes[1:]) + [fake_last_note]
                    )
                ]
            )

        return self.duration_cache

    def get_inputs(self) -> List[Note]:
        return self.notes

    def get_chord_change_indices(self) -> List[int]:
        return self.chord_changes

    def get_chord_ranges(self) -> List[Tuple[int, int]]:
        return self.chord_ranges

    def get_chords(self) -> List[Chord]:
        return self.chords

    def get_chord_note_inputs(
        self,
        window: int = 2,
        ranges: List[Tuple[int, int]] = None,
        change_indices: List[int] = None,
    ):
        use_real_chords = False

        if ranges is None:
            use_real_chords = True
            ranges = self.get_chord_ranges()
        if change_indices is None:
            use_real_chords = True
            change_indices = self.get_chord_change_indices()

        chords = self.get_chords() if use_real_chords else [None] * len(ranges)

        last_offset = self.chords[-1].offset
        duration_cache = self.get_duration_cache()

        chord_note_inputs = []
        for (onset_index, offset_index), change_index, chord in tqdm(
            zip(ranges, change_indices, chords),
            desc="Generating chord classification inputs",
            total=len(ranges),
        ):
            duration = (
                np.sum(duration_cache[change_index:offset_index])
                if chord is None
                else chord.duration
            )
            onset = self.notes[change_index].onset
            try:
                offset = self.notes[offset_index].onset
            except IndexError:
                offset = last_offset

            chord_note_inputs.append(
                get_chord_note_input(
                    self.notes,
                    self.measures_df,
                    onset,
                    offset,
                    duration,
                    change_index,
                    onset_index,
                    offset_index,
                    window,
                    duration_cache=duration_cache,
                    chord=chord,
                )
            )

        return chord_note_inputs

    def get_key_change_indices(self) -> List[int]:
        return self.key_changes

    def get_keys(self) -> List[Key]:
        return self.keys

    def to_dict(self) -> Dict[str, List]:
        return {
            "notes": [note.to_dict() for note in self.get_inputs()],
            "chords": [chord.to_dict() for chord in self.get_chords()],
            "keys": [key.to_dict() for key in self.get_keys()],
            "chord_changes": self.get_chord_change_indices(),
            "chord_ranges": self.get_chord_ranges(),
            "key_changes": self.get_key_change_indices(),
        }
