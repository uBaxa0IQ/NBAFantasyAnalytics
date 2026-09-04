"""ESPN slot rules shared by seasonal and draft calculations."""

from .projection import DEFAULT_LINEUP_SLOTS

SLOT_NAMES = {0: 'PG', 1: 'SG', 2: 'SF', 3: 'PF', 4: 'C', 5: 'G', 6: 'F',
              7: 'SG/SF', 8: 'G/F', 9: 'PF/C', 10: 'F/C', 11: 'UT', 12: 'BE',
              13: 'IR', 14: '', 15: 'Rookie'}


def league_slots(league_metadata, include_bench=False):
    league = league_metadata.league
    counts = getattr(getattr(league, 'settings', None), 'position_slot_counts', None)
    if counts is None:
        cached = getattr(league_metadata, '_active_slot_counts', None)
        if cached is not None:
            counts = cached
    if counts is None:
        raw = league.espn_request.league_get(params={'view': 'mSettings'})
        counts = raw.get('settings', {}).get('rosterSettings', {}).get('lineupSlotCounts')
        if counts is not None:
            league_metadata._active_slot_counts = counts
    if counts is None:
        return tuple(DEFAULT_LINEUP_SLOTS)
    slots = []
    for raw_slot, count in counts.items():
        slot = SLOT_NAMES.get(int(raw_slot), '') if str(raw_slot).isdigit() else str(raw_slot)
        slot = {'UTIL': 'UT', 'BENCH': 'BE'}.get(slot, slot)
        if slot in {'IR', 'IL', '', 'Rookie'} or (slot == 'BE' and not include_bench):
            continue
        if slot not in set(SLOT_NAMES.values()):
            raise ValueError(f'Unsupported ESPN lineup slot: {slot}')
        slots.extend([slot] * max(0, int(count)))
    return tuple(slots)
