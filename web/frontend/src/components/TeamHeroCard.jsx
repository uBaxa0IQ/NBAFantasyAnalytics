import React from 'react';
import TeamBalanceRadar from './TeamBalanceRadar';

const TeamHeroCard = ({ teamName, leaguePosition, teamId, period, excludeIr, compareTeamId, compareTeamName, teams, onCompareChange }) => {
    return (
        <div className="bg-white border rounded-lg p-6 shadow-sm">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Left side: Team name and position */}
                <div className="flex flex-col justify-center">
                    <h1 className="text-3xl font-bold text-gray-800 mb-2">{teamName}</h1>
                    {leaguePosition !== null && leaguePosition !== undefined && (
                        <div className="flex items-center gap-2">
                            <span className="text-lg text-gray-600">Позиция в лиге:</span>
                            <span className="text-2xl font-bold text-blue-600">#{leaguePosition}</span>
                        </div>
                    )}
                </div>

                {/* Right side: Radar chart */}
                <div>
                    <div className="flex items-center justify-between mb-4 flex-wrap gap-4">
                        <h3 className="text-lg font-semibold text-gray-700">Баланс команды по категориям</h3>
                        <div className="flex items-center gap-2">
                            <label className="text-sm text-gray-600">Сравнить с:</label>
                            <select
                                value={compareTeamId || ''}
                                onChange={(e) => onCompareChange(e.target.value)}
                                className="border p-2 rounded text-sm min-w-[200px]"
                            >
                                <option value="">Не сравнивать</option>
                                {teams
                                    .filter(team => team.team_id.toString() !== teamId?.toString())
                                    .map(team => (
                                        <option key={team.team_id} value={team.team_id}>
                                            {team.team_name}
                                        </option>
                                    ))}
                            </select>
                        </div>
                    </div>
                    <TeamBalanceRadar
                        teamId={teamId}
                        period={period}
                        excludeIr={excludeIr}
                        compareTeamId={compareTeamId || null}
                        compareTeamName={compareTeamName}
                    />
                </div>
            </div>
        </div>
    );
};

export default TeamHeroCard;




