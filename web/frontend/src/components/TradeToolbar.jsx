export default function TradeToolbar({ mode, onModeChange, children }) {
    return (
        <div className="mb-4 flex flex-wrap justify-between items-center gap-4">
            <div className="inline-flex rounded-lg border border-gray-300 bg-white p-1">
                {[['two-team', '2 команды'], ['multi-team', 'Мультикомандный']].map(([value, label]) => (
                    <button key={value} type="button" onClick={() => onModeChange(value)}
                        className={`px-4 py-2 rounded-md font-medium transition-colors ${mode === value ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'}`}>
                        {label}
                    </button>
                ))}
            </div>
            {children}
        </div>
    );
}
