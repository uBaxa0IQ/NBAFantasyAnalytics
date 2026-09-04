"""Freeze forecasts before a matchup; evaluate against completed ESPN results."""
import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from core.simulation import compare_category_stats


def connect():
    path = Path(os.getenv('FORECAST_DB', '.cache/forecasts.db'))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE IF NOT EXISTS forecasts (league INTEGER, season INTEGER, week INTEGER, team1 INTEGER, team2 INTEGER, period TEXT, categories TEXT, reverse_cats TEXT, prediction TEXT, actual TEXT, created TEXT, PRIMARY KEY(league,season,week,team1,team2,period))')
    return db


def record(league, season, week, team1, team2, period, stats1, stats2, categories, reverse):
    with connect() as db:
        db.execute('INSERT OR IGNORE INTO forecasts VALUES (?,?,?,?,?,?,?,?,?,NULL,?)',
                   (league, season, week, team1, team2, period, json.dumps(list(categories)), json.dumps(list(reverse)),
                    json.dumps([stats1, stats2]), datetime.now(timezone.utc).isoformat()))


def validate(league_metadata):
    with connect() as db:
        rows = db.execute('SELECT week,team1,team2,period,categories,reverse_cats,prediction,actual FROM forecasts WHERE league=? AND season=?',
                          (league_metadata.league_id, league_metadata.year)).fetchall()
        actual_weeks = {}
        errors, matches, correct = {}, 0, 0
        for week, left, right, period, raw_cats, raw_reverse, prediction, actual in rows:
            if actual is None and week < league_metadata.league.currentMatchupPeriod:
                if week not in actual_weeks:
                    actual_weeks[week] = league_metadata.get_all_teams_stats_for_week(week)
                teams = actual_weeks[week]
                if left in teams and right in teams:
                    actual = json.dumps([teams[left]['stats'], teams[right]['stats']])
                    db.execute('UPDATE forecasts SET actual=? WHERE league=? AND season=? AND week=? AND team1=? AND team2=? AND period=?',
                               (actual, league_metadata.league_id, league_metadata.year, week, left, right, period))
            if actual is None:
                continue
            predicted, observed = json.loads(prediction), json.loads(actual)
            cats, reverse = json.loads(raw_cats), json.loads(raw_reverse)
            for cat in cats:
                for i in (0, 1):
                    if cat in observed[i] and cat in predicted[i]:
                        errors.setdefault(cat, []).append(abs(predicted[i][cat] - observed[i][cat]))
            p = compare_category_stats(*predicted, cats, reverse)
            a = compare_category_stats(*observed, cats, reverse)
            def outcome(result):
                return (result['team1_wins'] > result['team2_wins']) - (result['team1_wins'] < result['team2_wins'])
            correct += outcome(p) == outcome(a)
            matches += 1
        return {'recorded': len(rows), 'resolved': matches, 'matchup_accuracy': correct / matches if matches else None,
                'category_mae': {cat: sum(values) / len(values) for cat, values in errors.items()},
                'note': 'Первые сохранённые прогнозы до начала недели. При нулевой выборке точность неизвестна.'}
