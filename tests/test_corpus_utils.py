"""Tests for corpu_utils.py"""
from fractions import Fraction
from typing import Tuple, List

import pandas as pd
import numpy as np

from harmonic_inference.utils import rhythmic_utils as ru
from harmonic_inference.utils import corpus_utils as cu
from harmonic_inference.data.corpus_reading import read_dump

CHORDS_TSV = 'corpus_data/chords.tsv'
NOTES_TSV = 'corpus_data/notes.tsv'
MEASURES_TSV = 'corpus_data/measures.tsv'

measures_df = read_dump(MEASURES_TSV)
chords_df = read_dump(CHORDS_TSV)
notes_df = read_dump(NOTES_TSV)

removed_repeats = cu.remove_repeats(measures_df, remove_unreachable=True)
removed_repeats_with_unreachable = cu.remove_repeats(measures_df, remove_unreachable=False)

# offsets_notes_df = cu.add_note_offsets(notes_df, removed_repeats)
# merged_notes_df = cu.merge_ties(offsets_notes_df, removed_repeats)


def test_remove_unmatched():
    # Chords
    chords_df_removed = cu.remove_unmatched(chords_df, removed_repeats)
    assert chords_df.index.name == chords_df_removed.index.name
    assert all(chords_df.columns == chords_df_removed.columns)
    assert len(chords_df_removed) <= len(chords_df)

    merged = pd.merge(chords_df.reset_index(), removed_repeats, how='inner', on=['file_id', 'mc'])
    merged = merged.set_index(['file_id', 'chord_id'])
    assert len(chords_df_removed) == len(merged)
    assert all(chords_df_removed.index == merged.index)

    assert chords_df.equals(cu.remove_unmatched(chords_df, removed_repeats_with_unreachable))

    # Notes
    notes_df_removed = cu.remove_unmatched(notes_df, removed_repeats)
    assert notes_df.index.name == notes_df_removed.index.name
    assert all(notes_df.columns == notes_df_removed.columns)
    assert len(notes_df_removed) <= len(notes_df)

    merged = pd.merge(notes_df.reset_index(), removed_repeats, how='inner', on=['file_id', 'mc'])
    merged = merged.set_index(['file_id', 'note_id'])
    assert len(notes_df_removed) == len(merged)
    assert all(notes_df_removed.index == merged.index)

    assert notes_df.equals(cu.remove_unmatched(notes_df, removed_repeats_with_unreachable))


def test_remove_repeats():
    def count_reachable(piece_df: pd.DataFrame, selected_mcs: List[int], start_mc: int) -> int:
        """
        Get a count of the ways to reach the given list of mcs from the start measure.

        Parameters
        ----------
        piece_df : pd.DataFrame
            The measures df of a single piece.
        selected_mcs : List[int]
            A list of mcs whose count to return.
        start_mc : int
            The starting measure mc of this piece.

        Returns
        -------
        count : int
            The number of different ways to reach any mc in the given selected_mcs list from the
            start measure.
        """
        if len(selected_mcs) == 0:
            return 0

        count = sum([1 for mc in selected_mcs if mc == start_mc])
        if count == len(selected_mcs):
            return count

        return count_reachable(piece_df, piece_df.loc[piece_df.next.isin(selected_mcs), 'mc'],
                               start_mc) + count

    # Test well-formedness
    for file_id, piece_df in removed_repeats.groupby('file_id'):
        piece_df = piece_df.copy()

        assert len(piece_df.loc[piece_df['next'].isnull()]) == 1, "Not exactly 1 mc ends."
        assert piece_df.next.dtype == 'Int64'

        # Check that every measure can be reached at most once
        assert piece_df.next.value_counts().max() == 1

        # Check that every measure can be reached except the start_mc
        assert set(piece_df.mc) - set(piece_df.next) == set([piece_df.iloc[0].mc])

        # Check that every measure points forwards (ensures no disjoint loops)
        assert len(piece_df.loc[piece_df.next <= piece_df.mc]) == 0

    # Test with unreachables
    assert len(removed_repeats_with_unreachable) > len(removed_repeats)

    # Test well-formedness
    for file_id, piece_df in removed_repeats_with_unreachable.groupby('file_id'):
        piece_df = piece_df.copy()

        assert len(piece_df.loc[piece_df['next'].isnull()]) == 1, "Not exactly 1 mc ends."
        assert piece_df.next.dtype == 'Int64'

        # Check that every measure can be reached at most once
        start_mc = piece_df.iloc[0].mc
        value_counts = piece_df.next.value_counts()

        for mc in value_counts[value_counts > 1].index:
            assert count_reachable(piece_df, piece_df.loc[piece_df.next == mc, 'mc'], start_mc) <= 1




def test_add_note_offsets():
    measures_dicts = [
        # No offsets
        pd.DataFrame({
            'mc': [1, 2, 3, 4, 5, 6, 7],
            'act_dur': [Fraction(1),
                        Fraction(1),
                        Fraction(1, 2),
                        Fraction(1),
                        Fraction(1, 2),
                        Fraction(1),
                        Fraction(1, 2)],
            'offset': [Fraction(0)] * 7,
            'next': [2, 3, 4, 6, 6, 7, pd.NA]
        }),
        # Offsets
        pd.DataFrame({
            'mc': [1, 2, 3, 4, 5, 6, 7],
            'act_dur': [Fraction(1, 2),
                        Fraction(1, 2),
                        Fraction(1, 4),
                        Fraction(1, 2),
                        Fraction(1, 4),
                        Fraction(1),
                        Fraction(1, 4)],
            'offset': [Fraction(1, 2),
                       Fraction(1, 2),
                       Fraction(1, 4),
                       Fraction(1, 2),
                       Fraction(1, 4),
                       Fraction(0),
                       Fraction(1, 4)],
            'next': [2, 3, 4, 6, 6, 7, pd.NA]
        }),
        pd.DataFrame({ # Alternate offsets
            'mc': [1, 2, 3, 4, 5, 6, 7],
            'act_dur': [Fraction(1),
                        Fraction(1),
                        Fraction(1, 2),
                        Fraction(1),
                        Fraction(1, 2),
                        Fraction(1),
                        Fraction(1, 2)],
            'offset': [Fraction(0),
                       Fraction(1, 2),
                       Fraction(1, 4),
                       Fraction(1, 2),
                       Fraction(1, 4),
                       Fraction(0),
                       Fraction(0)],
            'next': [2, 3, 4, 6, 6, 7, pd.NA]
        })
    ]
    measures = pd.concat(
        measures_dicts, keys=[0, 1, 2], axis=0, names=['file_id', 'measure_id']
    )

    def check_result(note: pd.DataFrame, target_offset_mc: int, target_offset_beat: Fraction):
        """
        Check the result of a call to cu.add_note_offsets with assertions.

        Parameters
        ----------
        note : pd.DataFrame
            A DataFrame with a single note, including offset_mc and offset_beat columns from
            cu.add_note_offsets.
        target_offset_mc : int
            The correct offset_mc for the note.
        target_offset_beat : Fraction
            The correct offset_beat for the note.
        """
        note_offset = cu.add_note_offsets(note, measures)

        # Check values
        assert note.equals(note_offset.loc[:, ['mc', 'onset', 'duration']])
        assert target_offset_mc == note_offset.offset_mc.values[0]
        assert target_offset_beat == note_offset.offset_beat.values[0]

        # Check with rhythmic utils
        assert ru.get_range_length(
            (note.mc.values[0], note.onset.values[0]), (target_offset_mc, target_offset_beat),
            measures.loc[note.index.get_level_values('file_id')]
        ) == note.duration.values[0]

        # Check types
        assert isinstance(note_offset.offset_beat.values[0], Fraction)
        assert note_offset.offset_mc.dtype == 'Int64'
        assert note_offset.offset_beat.dtype == Fraction

        # Check structure of result
        assert set(note_offset.columns) == set(
            ['mc', 'onset', 'duration', 'offset_mc', 'offset_beat']
        )
        assert note_offset.index.names == ['file_id', 'note_id']
        assert len(note_offset) == len(note)

    # Tests without offset
    # In same measure
    note = pd.DataFrame({
        'file_id': [0],
        'note_id': [0],
        'mc': [1],
        'onset': [Fraction(0)],
        'duration': [Fraction(3, 4)]
    }).set_index(['file_id', 'note_id'])
    target_offset_mc = 1
    target_offset_beat = Fraction(3, 4)

    check_result(note, target_offset_mc, target_offset_beat)

    # One measure long
    note = pd.DataFrame({
        'file_id': [0],
        'note_id': [0],
        'mc': [1],
        'onset': [Fraction(3, 4)],
        'duration': [Fraction(1, 4)]
    }).set_index(['file_id', 'note_id'])
    target_offset_mc = 2
    target_offset_beat = Fraction(0)

    check_result(note, target_offset_mc, target_offset_beat)

    # Multiple measures
    note = pd.DataFrame({
        'file_id': [0],
        'note_id': [0],
        'mc': [1],
        'onset': [Fraction(0)],
        'duration': [Fraction(20)]
    }).set_index(['file_id', 'note_id'])
    target_offset_mc = 7
    target_offset_beat = Fraction(31, 2)

    check_result(note, target_offset_mc, target_offset_beat)

    # Tests with offsets
    # In same measure
    note = pd.DataFrame({
        'file_id': [1],
        'note_id': [0],
        'mc': [1],
        'onset': [Fraction(1, 2)],
        'duration': [Fraction(1, 4)]
    }).set_index(['file_id', 'note_id'])
    target_offset_mc = 1
    target_offset_beat = Fraction(3, 4)

    check_result(note, target_offset_mc, target_offset_beat)

    # One measure long
    note = pd.DataFrame({
        'file_id': [1],
        'note_id': [0],
        'mc': [1],
        'onset': [Fraction(1, 2)],
        'duration': [Fraction(1, 2)]
    }).set_index(['file_id', 'note_id'])
    target_offset_mc = 2
    target_offset_beat = Fraction(1, 2)

    check_result(note, target_offset_mc, target_offset_beat)

    # One+ measure
    note = pd.DataFrame({
        'file_id': [1],
        'note_id': [0],
        'mc': [1],
        'onset': [Fraction(1, 2)],
        'duration': [Fraction(3, 4)]
    }).set_index(['file_id', 'note_id'])
    target_offset_mc = 2
    target_offset_beat = Fraction(3, 4)

    check_result(note, target_offset_mc, target_offset_beat)

    # Many measures
    note = pd.DataFrame({
        'file_id': [1],
        'note_id': [0],
        'mc': [1],
        'onset': [Fraction(1, 2)],
        'duration': [Fraction(20)]
    }).set_index(['file_id', 'note_id'])
    target_offset_mc = 7
    target_offset_beat = Fraction(35, 2)

    check_result(note, target_offset_mc, target_offset_beat)


def test_get_notes_during_chord():
    def comes_before(t1_loc: Tuple[int, Fraction], t2_loc: Tuple[int, Fraction]) -> bool:
        t1_mc, t1_beat = t1_loc
        t2_mc, t2_beat = t2_loc
        if t1_mc < t2_mc:
            return True
        if t1_mc > t2_mc:
            return False
        return t1_beat < t2_beat

    num_tests = 1000
    indexes = np.random.randint(low=0, high=len(chords_df), size=num_tests)
    return_sizes = []
    return_non_onsets = []

    for i in indexes:
        chord = chords_df.iloc[i]
        notes = cu.get_notes_during_chord(chord, offsets_notes_df)
        return_sizes.append(len(notes))
        return_non_onsets.append(0)
        for _, note in notes.iterrows():
            if pd.isna(note.overlap):
                # Note onset is not before chord
                assert not comes_before((note.mc, note.onset), (chord.mc, chord.onset))
                # Note offset is not after chord
                assert not comes_before((chord.mc_next, chord.onset_next),
                                        (note.offset_mc, note.offset_beat))

            elif note.overlap == -1:
                return_non_onsets[-1] += 1
                # Note onset is before chord
                assert comes_before((note.mc, note.onset), (chord.mc, chord.onset))
                # Note offset is not after chord
                assert not comes_before((chord.mc_next, chord.onset_next),
                                        (note.offset_mc, note.offset_beat))

            elif note.overlap == 0:
                return_non_onsets[-1] += 1
                # Note onset is before chord
                assert comes_before((note.mc, note.onset), (chord.mc, chord.onset))
                # Note offset is after chord
                assert comes_before((chord.mc_next, chord.onset_next),
                                    (note.offset_mc, note.offset_beat))

            elif note.overlap == 1:
                # Note onset is not before chord
                assert not comes_before((note.mc, note.onset), (chord.mc, chord.onset))
                # Note offset is after chord
                assert comes_before((chord.mc_next, chord.onset_next),
                                    (note.offset_mc, note.offset_beat))

            else:
                assert False, "Invalid overlap value returned: " + str(note.overlap)

    for list_index, i in enumerate(indexes):
        chord = chords_df.iloc[i]
        notes = cu.get_notes_during_chord(chord, offsets_notes_df, onsets_only=True)
        assert len(notes) == return_sizes[list_index] - return_non_onsets[list_index], (
            "Length of returned df incorrect with onsets_only"
        )
        for _, note in notes.iterrows():
            if pd.isna(note.overlap):
                # Note onset is not before chord
                assert not comes_before((note.mc, note.onset), (chord.mc, chord.onset))
                # Note offset is not after chord
                assert not comes_before((chord.mc_next, chord.onset_next),
                                        (note.offset_mc, note.offset_beat))

            elif note.overlap == -1:
                assert False, "onsets_only returned an overlap -1"

            elif note.overlap == 0:
                assert False, "onsets_only returned an overlap 0"

            elif note.overlap == 1:
                # Note onset is not before chord
                assert not comes_before((note.mc, note.onset), (chord.mc, chord.onset))
                # Note offset is after chord
                assert comes_before((chord.mc_next, chord.onset_next),
                                    (note.offset_mc, note.offset_beat))

            else:
                assert False, "Invalid overlap value returned: " + str(note.overlap)
