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
    existing = {row[1] for row in db.execute('PRAGMA table_info(forecasts)')}
    for name, kind in (
        ('p_win', 'REAL'), ('p_tie', 'REAL'), ('p_loss', 'REAL'),
        ('engine_version', 'TEXT'), ('seed', 'INTEGER'), ('trials', 'INTEGER'),
    ):
        if name not in existing:
            db.execute(f'ALTER TABLE forecasts ADD COLUMN {name} {kind}')
    return db


def record(league, season, week, team1, team2, period, stats1, stats2, categories, reverse, odds=None):
    with connect() as db:
        odds = odds or {}
        db.execute('''INSERT OR IGNORE INTO forecasts
            (league,season,week,team1,team2,period,categories,reverse_cats,prediction,actual,created,
             p_win,p_tie,p_loss,engine_version,seed,trials)
            VALUES (?,?,?,?,?,?,?,?,?,NULL,?,?,?,?,?,?,?)''',
            (league, season, week, team1, team2, period, json.dumps(list(categories)), json.dumps(list(reverse)),
             json.dumps([stats1, stats2]), datetime.now(timezone.utc).isoformat(), odds.get('p_win'),
             odds.get('p_tie'), odds.get('p_loss'), odds.get('engine_version'), odds.get('seed'), odds.get('trials')))


def validate(league_metadata):
    with connect() as db:
        rows = db.execute('SELECT week,team1,team2,period,categories,reverse_cats,prediction,actual,p_win,p_tie,p_loss FROM forecasts WHERE league=? AND season=?',
                          (league_metadata.league_id, league_metadata.year)).fetchall()
        actual_weeks = {}
        errors, matches, point_matches, correct, brier_values = {}, 0, 0, 0, []
        for week, left, right, period, raw_cats, raw_reverse, prediction, actual, p_win, p_tie, p_loss in rows:
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
            a = compare_category_stats(*observed, cats, reverse)
            def outcome(result):
                return (result['team1_wins'] > result['team2_wins']) - (result['team1_wins'] < result['team2_wins'])
            if predicted[0] or predicted[1]:
                p = compare_category_stats(*predicted, cats, reverse)
                correct += outcome(p) == outcome(a)
                point_matches += 1
            if p_win is not None:
                observed_outcome = outcome(a)
                targets = (1.0 if observed_outcome > 0 else 0.0, 1.0 if observed_outcome == 0 else 0.0, 1.0 if observed_outcome < 0 else 0.0)
                probabilities = (float(p_win), float(p_tie or 0.0), float(p_loss or 0.0))
                brier_values.append(sum((probability - target) ** 2 for probability, target in zip(probabilities, targets)) / 3.0)
            matches += 1
        return {'recorded': len(rows), 'resolved': matches, 'matchup_accuracy': correct / point_matches if point_matches else None,
                'category_mae': {cat: sum(values) / len(values) for cat, values in errors.items()},
                'brier_score': sum(brier_values) / len(brier_values) if brier_values else None,
                'probabilistic_resolved': len(brier_values),
                'note': 'Первые сохранённые прогнозы до начала недели. При нулевой выборке точность неизвестна.'}
