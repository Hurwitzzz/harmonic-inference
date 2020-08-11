"""Utility functions for getting rhythmic or metrical information from the corpus DataFrames."""

from typing import TypeVar, Tuple
from fractions import Fraction
import pandas as pd

Beat = TypeVar(Tuple[int, Fraction])
TripleFraction = TypeVar(Fraction, Fraction, Fraction)

def get_range_length(range_start: Beat, range_end: Beat, measures: pd.DataFrame) -> Fraction:
    """
    Get the length of a range in whole notes.

    Parameters
    ----------
    range_start : tuple(int, Fraction)
        A tuple of (mc, beat) values of the start of the range.

    range_end : tuple(int, Fraction)
        A tuple of (mc, beat) values of the end of the range.

    measures : pd.DataFrame
        A DataFrame containing the measures info for this particulad piece id.

    Returns
    -------
    length : Fraction
        The length of the given range, in whole notes.
    """
    start_mc, start_beat = range_start
    end_mc, end_beat = range_end

    if start_mc == end_mc:
        return end_beat - start_beat

    # Start looping at end of start_mc
    length, current_mc = measures.loc[start_mc, ['act_dur', 'next']]
    length -= start_beat

    # Loop until reaching end_mc
    while current_mc != end_mc and current_mc is not None:
        length += measures.loc[current_mc, 'act_dur']
        current_mc = measures.loc[current_mc, 'next']

    # Add remainder
    length += end_beat

    return length




def get_rhythmic_info_as_proportion_of_range(note: pd.Series, range_start: Beat,
                                             range_end: Beat, measures: pd.DataFrame,
                                             range_len: Fraction = None) -> TripleFraction:
    """
    Get a note's onset, offset, and duration as a proportion of the given range.

    Parameters
    ----------
    note : pd.Series
        The note whose onset offset and duration this will return.

    range_start : tuple(int, Fraction)
        A tuple of (mc, beat) values of the start of the range.

    range_end : tuple(int, Fraction)
        A tuple of (mc, beat) values of the end of the range.

    measures : pd.DataFrame
        A DataFrame containing the measures info for the the corpus.

    range_len : Fraction
        The total duration of the given range, if it is known.

    Returns
    -------
    onset : Fraction
        The onset of the note, as a proportion of the given range.

    offset : Fraction
        The offset of the note, as a proportion of the given range.

    duration : Fraction
        The duration of the note, as a proportion of the given range.
    """
    if range_len is None:
        range_len = get_range_length(range_start, range_end, measures)

    duration = note.duration / range_len
    onset = get_range_length(range_start, (note.mc, note.onset), measures) / range_len
    offset = onset + duration

    return onset, offset, duration




def get_metrical_level_lengths(timesig: str) -> TripleFraction:
    """
    Get the lengths of the beat and subbeat levels of the given time signature.

    Parameters
    ----------
    timesig : string
        A string representation of the time signature as "numerator/denominator".

    Returns
    -------
    measure_length : Fraction
        The length of a measure in the given time signature, where 1 is a whole note.

    beat_length : Fraction
        The length of a beat in the given time signature, where 1 is a whole note.

    sub_beat_length : Fraction
        The length of a sub_beat in the given time signature, where 1 is a whole note.
    """
    numerator, denominator = [int(val) for val in timesig.split('/')]

    if (numerator > 3) and (numerator % 3 == 0):
        # Compound meter
        sub_beat_length = Fraction(1, denominator)
        beat_length = sub_beat_length * 3
    else:
        # Simple meter
        beat_length = Fraction(1, denominator)
        sub_beat_length = beat_length / 2

    return Fraction(numerator, denominator), beat_length, sub_beat_length



def get_metrical_level(beat: Fraction, measure: pd.Series) -> int:
    """
    Get the metrical level of a given beat.

    Parameters
    ----------
    beat : Fraction
        The beat we are interested in within the measure. 1 corresponds to a whole
        note after the downbeat.

    measure : pd.Series
        The measures_df row of the corresponding mc.

    Returns
    -------
    level : int
        An int representing the metrical level of the given beat:
        3: downbeat
        2: beat
        1: sub-beat
        0: lower
    """
    measure_length, beat_length, sub_beat_length = get_metrical_level_lengths(measure.timesig)

    # Offset for partial measures (not beginning on a downbeat)
    beat += measure.offset

    if beat % measure_length == 0:
        return 3
    if beat % beat_length == 0:
        return 2
    if beat % sub_beat_length == 0:
        return 1
    return 0