export const espnDraftRank = player => {
    const rank = Number(player?.espn_roto_rank);
    return Number.isFinite(rank) && rank > 0 ? rank : null;
};

export const compareEspnDraftRank = (left, right, direction = 'asc') => {
    const leftRank = espnDraftRank(left);
    const rightRank = espnDraftRank(right);
    if (leftRank == null) return rightRank == null ? 0 : 1;
    if (rightRank == null) return -1;
    return direction === 'asc' ? leftRank - rightRank : rightRank - leftRank;
};
