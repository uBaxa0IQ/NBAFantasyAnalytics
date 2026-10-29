import { useEffect, useRef, useState } from 'react';
import { loadState, StorageKeys } from '../utils/statePersistence';

const samePlayers = (left, right) => left.length === right.length && left.every(name => right.includes(name));
const sameTrade = (left, right) => String(left.myTeam) === String(right.myTeam)
    && String(left.theirTeam) === String(right.theirTeam)
    && samePlayers(left.selectedGive, right.selectedGive)
    && samePlayers(left.selectedReceive, right.selectedReceive);

const isPlayerList = value => Array.isArray(value) && value.every(name => typeof name === 'string');

export default function SavedTrades({ draft, onOpen, disabled = false }) {
    const [trades, setTrades] = useState(() => {
        const stored = loadState(StorageKeys.SAVED_TRADES, []);
        return Array.isArray(stored) ? stored.filter(trade => trade && typeof trade.id === 'string'
            && typeof trade.title === 'string' && trade.myTeam && trade.theirTeam
            && isPlayerList(trade.selectedGive) && isPlayerList(trade.selectedReceive)) : [];
    });
    const [open, setOpen] = useState(false);
    const [error, setError] = useState('');
    const root = useRef(null);
    const trigger = useRef(null);
    const current = trades.find(trade => sameTrade(trade, draft));
    const canSave = draft.myTeam && draft.theirTeam && String(draft.myTeam) !== String(draft.theirTeam)
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
            localStorage.setItem(StorageKeys.SAVED_TRADES, JSON.stringify(next));
            setTrades(next);
            setError('');
        } catch {
            setError('Не удалось сохранить изменения');
        }
    };

    const save = () => {
        if (!canSave || current || disabled) return;
        persist([...trades, {
            ...draft,
            id: crypto.randomUUID(),
            title: `${draft.selectedGive.join(' + ')} → ${draft.selectedReceive.join(' + ')}`,
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
                <div id="saved-trades-list" className="absolute left-0 sm:left-auto sm:right-0 top-full mt-2 z-30 w-80 max-w-[calc(100vw-8rem)] sm:max-w-[calc(100vw-3rem)] max-h-80 overflow-y-auto rounded border border-gray-200 bg-white p-1">
                    {trades.length === 0 && <div className="px-3 py-3 text-sm text-gray-400">Нет сохранённых трейдов</div>}
                    {trades.map(trade => (
                        <div key={trade.id} className={`flex items-center rounded ${current?.id === trade.id ? 'bg-blue-50' : 'hover:bg-gray-50'}`}>
                            <button type="button" onClick={() => { onOpen(trade); setOpen(false); trigger.current?.focus(); }}
                                className="flex-1 min-w-0 px-3 py-3 text-sm text-left text-gray-700 break-words disabled:opacity-50">
                                {trade.title}
                            </button>
                            <button type="button" aria-label={`Удалить ${trade.title}`} onClick={() => persist(trades.filter(item => item.id !== trade.id))}
                                className="px-2 py-2 text-xs text-gray-400 hover:text-red-600 shrink-0">Удалить</button>
                        </div>
                    ))}
                </div>
            )}
            {error && <div role="alert" className="absolute right-0 top-full mt-1 text-xs text-red-600 bg-white">{error}</div>}
        </div>
    );
}
