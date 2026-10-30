import { useEffect, useRef, useState } from 'react';
import { loadState, StorageKeys } from '../utils/statePersistence';

const samePlayers = (left, right) => left.length === right.length && left.every(name => right.includes(name));
const sameTrade = (left, right) => String(left.myTeam) === String(right.myTeam)
    && String(left.theirTeam) === String(right.theirTeam)
    && samePlayers(left.selectedGive, right.selectedGive)
    && samePlayers(left.selectedReceive, right.selectedReceive);

const isPlayerList = value => Array.isArray(value) && value.every(name => typeof name === 'string');

export default function SavedTrades({ draft, onOpen, disabled = false, mode = 'two-team', teams = [] }) {
    const multi = mode === 'multi-team';
    const storageKey = multi ? StorageKeys.SAVED_MULTITEAM_TRADES : StorageKeys.SAVED_TRADES;
    const [trades, setTrades] = useState(() => {
        const stored = loadState(storageKey, []);
        return Array.isArray(stored) ? stored.filter(trade => trade && typeof trade.id === 'string'
            && typeof trade.title === 'string' && (multi
                ? Array.isArray(trade.teamTrades) && trade.teamTrades.length >= 2
                    && trade.teamTrades.every(item => item && item.teamId && isPlayerList(item.give) && isPlayerList(item.receive))
                : trade.myTeam && trade.theirTeam && isPlayerList(trade.selectedGive) && isPlayerList(trade.selectedReceive))) : [];
    });
    const [open, setOpen] = useState(false);
    const [error, setError] = useState('');
    const root = useRef(null);
    const trigger = useRef(null);
    const teamName = id => teams.find(team => String(team.team_id) === String(id))?.team_name || `Команда ${id}`;
    const current = trades.find(trade => multi
        ? trade.teamTrades.length === draft.teamTrades.length && trade.teamTrades.every(item => {
            const other = draft.teamTrades.find(candidate => String(candidate.teamId) === String(item.teamId));
            return other && samePlayers(item.give, other.give) && samePlayers(item.receive, other.receive);
        }) : sameTrade(trade, draft));
    const canSave = multi
        ? draft.teamTrades.length >= 2 && draft.teamTrades.every(item => item.teamId && (item.give.length || item.receive.length))
            && new Set(draft.teamTrades.map(item => String(item.teamId))).size === draft.teamTrades.length
        : draft.myTeam && draft.theirTeam && String(draft.myTeam) !== String(draft.theirTeam)
            && draft.selectedGive.length > 0 && draft.selectedReceive.length > 0;

    useEffect(() => {
        if (!open) return;
        const outside = event => {
            if (!root.current?.contains(event.target)) setOpen(false);
        };
        const escape = event => {
            if (event.key === 'Escape') {
                setOpen(false);
                trigger.current?.focus();
            }
        };
        document.addEventListener('pointerdown', outside);
        document.addEventListener('keydown', escape);
        return () => {
            document.removeEventListener('pointerdown', outside);
            document.removeEventListener('keydown', escape);
        };
    }, [open]);

    const persist = next => {
        try {
            localStorage.setItem(storageKey, JSON.stringify(next));
            setTrades(next);
            setError('');
        } catch {
            setError('Не удалось сохранить изменения');
        }
    };

    const save = () => {
        if (!canSave || current || disabled) return;
        persist([...trades, {
            ...JSON.parse(JSON.stringify(draft)),
            id: crypto.randomUUID(),
            title: multi
                ? draft.teamTrades.map(item => `${item.give.join(' + ') || '—'} → ${item.receive.join(' + ') || '—'}`).join(' · ')
                : `${draft.selectedGive.join(' + ')} → ${draft.selectedReceive.join(' + ')}`,
        }]);
    };

    return (
        <div ref={root} className="relative flex items-center gap-4">
            <button type="button" onClick={save} disabled={!canSave || !!current || disabled}
                className="px-3 py-1.5 border border-gray-300 rounded bg-white text-sm text-gray-700 hover:bg-gray-50 disabled:text-gray-400 disabled:cursor-default">
                {current ? 'Сохранён' : 'Сохранить трейд'}
            </button>
            <button ref={trigger} type="button" aria-expanded={open} aria-controls="saved-trades-list"
                onClick={() => setOpen(value => !value)} className="py-1.5 text-sm text-gray-500 hover:text-blue-600 whitespace-nowrap">
                Сохранённые · {trades.length} <span aria-hidden="true">▾</span>
            </button>
            {open && (
                <div id="saved-trades-list" className="absolute left-0 sm:left-auto sm:right-0 top-full mt-2 z-30 w-[40rem] max-w-[calc(100vw-8rem)] sm:max-w-[calc(100vw-6rem)] max-h-[70vh] overflow-y-auto rounded-lg border border-gray-200 bg-white p-1">
                    {trades.length === 0 && <div className="px-3 py-3 text-sm text-gray-400">Нет сохранённых трейдов</div>}
                    {trades.map(trade => (
                        <div key={trade.id} className={`rounded border-b border-gray-200 last:border-b-0 ${current?.id === trade.id ? 'bg-blue-50' : 'hover:bg-gray-50'}`}>
                            <button type="button" aria-label={trade.title} onClick={() => { onOpen(trade); setOpen(false); trigger.current?.focus(); }}
                                className="block w-full px-3 pt-3 pb-1 text-sm text-left text-gray-700 break-words rounded focus-visible:outline-blue-500">
                                <span className="hidden sm:grid grid-cols-[minmax(0,0.9fr)_minmax(0,1fr)_minmax(0,1fr)] gap-4 pb-1 text-xs text-gray-400">
                                    <span>Команда</span><span>Отдаёт</span><span>Получает</span>
                                </span>
                                {(multi ? trade.teamTrades : [
                                    { teamId: trade.myTeam, give: trade.selectedGive, receive: trade.selectedReceive },
                                    { teamId: trade.theirTeam, give: trade.selectedReceive, receive: trade.selectedGive },
                                ]).map(item => (
                                    <span key={item.teamId} className="grid grid-cols-2 sm:grid-cols-[minmax(0,0.9fr)_minmax(0,1fr)_minmax(0,1fr)] gap-x-4 gap-y-1 py-2 border-t border-gray-200 first:border-t-0">
                                        <span className="col-span-2 sm:col-span-1 font-medium text-gray-800 min-w-0">{teamName(item.teamId)}</span>
                                        <span className="min-w-0">
                                            <span className="block sm:hidden mb-1 text-xs text-gray-400">Отдаёт</span>
                                            {item.give.length ? item.give.map(name => <span key={name} className="block">{name}</span>) : '—'}
                                        </span>
                                        <span className="min-w-0">
                                            <span className="block sm:hidden mb-1 text-xs text-gray-400">Получает</span>
                                            {item.receive.length ? item.receive.map(name => <span key={name} className="block">{name}</span>) : '—'}
                                        </span>
                                    </span>
                                ))}
                            </button>
                            <div className="flex justify-end px-2 pb-1">
                            <button type="button" aria-label={`Удалить ${trade.title}`} onClick={() => persist(trades.filter(item => item.id !== trade.id))}
                                className="px-2 py-1 text-xs text-gray-400 hover:text-red-600 shrink-0">Удалить</button>
                            </div>
                        </div>
                    ))}
                </div>
            )}
            {error && <div role="alert" className="absolute right-0 top-full mt-1 text-xs text-red-600 bg-white">{error}</div>}
        </div>
    );
}
