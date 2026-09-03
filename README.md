# NBA Fantasy Analytics

NBA Fantasy Analytics is a full-stack web application for ESPN Fantasy Basketball managers who want to make data-driven roster, trade, and matchup decisions.

It combines league data, player-level metrics, and custom scoring logic to provide practical tools for weekly lineup management and season strategy.

## Overview

The application helps answer questions such as:

- How strong is my team across all 11 categories?
- Which free agent produces the largest real add/drop gain this week?
- Is a proposed trade improving or weakening my competitive position?
- What are my expected results against every team in the league?
- Who should I take with the next pick in a live ESPN draft?

## Key Features

### Team Dashboard

- Team snapshot with key indicators and top contributors
- Current matchup breakdown by category winners
- Team balance radar chart
- Player position history and injured players list
- Full Punt Analyzer that compares all 1,024 viable strategies from zero to five punt categories
- Core control, opponent coverage, error margin, risk, and multi-category strategy application

### Team Analytics

- Player and team Z-score analysis
- Time-window filters (season, last 30/15/7 days, projections)
- Punt-category support for strategy modeling
- Separate general and strategy-adjusted Z-score when punt categories are active
- Optional exclusion of IR players for fairer comparisons
- Daily lineup optimization by NBA schedule and valid ESPN slots

### Trade Analysis

- Before/after comparison for multi-player trades
- Team-level and trade-participant-only modes
- Estimated impact on league standing
- Remaining-calendar impact for both teams, including slot competition
- Multi-team trade support

### Matchup Simulation

- League-wide simulation in three modes:
  - Matchup results-based
  - Schedule projection with daily lineup optimization
  - Z-score-based

### Player Tools

- Full player pool with advanced metrics
- Team-specific free-agent add/drop recommendations
- Side-by-side comparison (up to five players)
- Detailed player cards

### Playoffs and Live Draft

- Playoff periods and bracket type are derived from ESPN league settings
- Championship, placement, and consolation paths are kept separate
- Before the draft, the application becomes Draft Prep with a projected board, virtual roster, build directions, positional scarcity, and a queue shared with the live room
- Draft Prep separates universal planning from pick-specific availability depending on whether ESPN has published the snake order
- ESPN Live Draft Trends data is loaded directly from the player market response: ADP, seven-day movement, ROTO rank, auction value, and roster percentage
- Before the order is known, the draft model simulates every snake slot in an interactive position selector; a selected slot receives a 240-run full-league analysis with coherent rosters, category wins, projected strength rank, top-N strength rate, availability, and selection frequency
- Draft Simulation includes a paired ESPN-projection benchmark comparing pure ROTO drafting, the balanced advisor, and punt FG%; every strategy sees the same market scenarios and is evaluated across every league category
- Live advice is limited to six actionable names: one primary pick, two take-now options, two players who can wait, and one fallback. The primary pick includes paired-simulation confidence, expected category gain, and a 95% interval.
- Live lookahead and offline draft benchmarks use an independent projected-volume evaluator (`per-game × GP`) and ESPN's exact roster slots, including multi-position eligibility.
- `GET /api/draft/punt-benchmark/{team_id}` exhaustively screens punt combinations for standard 8-cat (`max_punts=2`, 37 strategies) or the custom 11-cat format (`format=custom11&max_punts=3`, 232 strategies), then retests finalists across every draft slot.
- With no manually selected punt, Draft Room uses an adaptive portfolio of benchmark-derived strategies. It updates strategy probabilities after every pick and ranks candidates by projected marginal volume, market value, roster fit, and cross-strategy robustness. Selecting any Punt Category in Settings locks a manual strategy instead.
- `GET /api/draft/adaptive-benchmark/{team_id}` compares the adaptive policy with the legacy balanced and best fixed-punt policies against a mixed self-play population, including a held-out projection stress test.
- Live draft decisions and subsequent actual picks are recorded locally in the ignored `draft_learning.db`; `GET /api/draft/learning-stats` reports dataset size for future policy training.
- The opt-in offline value/policy training pipeline is documented in [`docs/draft-ml-training.md`](docs/draft-ml-training.md). Generation, training, evaluation, benchmarking, and promotion require an explicit `--execute` flag.
- Draft and post-draft player views include games played from the displayed statistics season as a compact availability-history signal
- During an active ESPN draft the normal application automatically becomes a read-only Draft Room
- Draft Room conditions the simulation on completed picks and includes on-the-clock state, personal pick timing, roster construction, category balance, queue, recent picks, and recommendations
- After the draft and before scoring begins, a separate post-draft review shows roster power rank, category ranks, ADP value, reaches, strengths, weaknesses, and available players

## Tech Stack

- Backend: Python, FastAPI, Uvicorn
- Frontend: React (Vite), Axios, Recharts, Tailwind CSS
- Infrastructure: Docker, Docker Compose, Nginx
- Data source: ESPN Fantasy Basketball API (via authenticated cookies)

## Architecture

- `web/backend`: API endpoints, business logic orchestration, league data processing
- `core`: immutable league snapshots, projections, playoff logic, simulation, and Z-scores
- `web/frontend`: single-page application and data visualizations
- `nginx`: reverse-proxy configuration for containerized deployment

Data flow:

1. Frontend requests analytics via REST API.
2. Backend creates one consistent league snapshot per calculation.
3. Calendar projections optimize PG/SG/SF/PF/C/G/F/UTIL slots for every scoring day.
4. Processed metrics are returned to the frontend for interactive exploration.

## Getting Started

### Prerequisites

- Docker 20.10+ and Docker Compose 2.0+ (recommended)
- or Python 3.10+ and Node.js 18+ for local development
- Access to an ESPN Fantasy Basketball league

### Environment Variables

Create `.env` in the repository root:

```env
LEAGUE_ID=your_league_id_here
SEASON_YEAR=2027
DEFAULT_TEAM_ID=your_team_id_here
ESPN_S2=your_espn_s2_token_here
SWID={your-swid-guid-here}
```

`DEFAULT_TEAM_ID` можно оставить пустым: тогда будет выбрана первая команда лиги. Значение `SEASON_YEAR` должно совпадать с годом, который ESPN использует для нужного сезона.

How to obtain `ESPN_S2` and `SWID`:

1. Sign in to ESPN Fantasy Basketball.
2. Open browser developer tools.
3. Go to Application/Storage -> Cookies.
4. Copy `espn_s2` and `SWID` values.

### Run with Docker

Перед запуском проверьте конфигурацию безопасной командой (значения cookies она не выводит):

```bash
python -m core.readiness
```

- Windows: `docker-start.bat`
- Linux/macOS: `./docker-start.sh`
- Direct command: `docker-compose up -d`

App URLs:

- Application: `http://localhost`
- Backend API through Nginx: `http://localhost/api`

### Run Locally

Backend:

```bash
pip install -r requirements.txt
uvicorn web.backend.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd web/frontend
npm install
npm run dev
```

## Configuration

- League ID, season year and default team are configured in `.env`.
- Statistical periods are generated automatically for the selected season; saved browser settings from an older season are migrated on startup.
- Frontend preferences are stored in browser `localStorage`.
- Period selection and weighted-period coefficients are available in common Settings.
- Settings can switch between the classic averages/Z-score engine and the calendar/lineup engine.
- Backend runtime and service-related settings are in `web/backend/config.py`.

## API Overview

Main endpoint groups are located in `web/backend/routers`:

- `dashboard`
- `analytics`
- `players`
- `trades`
- `simulation`
- `playoff`
- `lineup`
- `settings`
- `projections`
- `draft`

## Project Structure

```text
.
├─ core/
├─ nginx/
├─ web/
│  ├─ backend/
│  ├─ core/
│  └─ frontend/
├─ docker-compose.yml
├─ Dockerfile.backend
└─ README.md
```

## Development Checks

```bash
pip install -r requirements-dev.txt
python -m pytest
cd web/frontend
npm run lint
npm run build
```

## Limitations and Future Improvements

- ESPN private leagues require valid session cookies.
- Data freshness depends on ESPN API availability and league updates.
- Live Draft is intentionally read-only; it never submits a pick to ESPN.
- Waiver calendar gain is meaningful during an active matchup; after season completion the last matchup is used only as a fallback preview.

## Contributing

Contributions, issue reports, and improvement ideas are welcome.

## License

This project is licensed under the MIT License. See `LICENSE` for details.
