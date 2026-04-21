# NBA Fantasy Analytics

NBA Fantasy Analytics is a full-stack web application for ESPN Fantasy Basketball managers who want to make data-driven roster, trade, and matchup decisions.

It combines league data, player-level metrics, and custom scoring logic to provide practical tools for weekly lineup management and season strategy.

## Overview

The application helps answer questions such as:

- How strong is my team across all 11 categories?
- Which free agents fit my current category strategy?
- Is a proposed trade improving or weakening my competitive position?
- What are my expected results against every team in the league?

## Key Features

### Team Dashboard

- Team snapshot with key indicators and top contributors
- Current matchup breakdown by category winners
- Team balance radar chart
- Player position history and injured players list

### Team Analytics

- Player and team Z-score analysis
- Time-window filters (season, last 30/15/7 days, projections)
- Punt-category support for strategy modeling
- Optional exclusion of IR players for fairer comparisons
- Lineup optimization tools

### Trade Analysis

- Before/after comparison for multi-player trades
- Team-level and trade-participant-only modes
- Estimated impact on league standing
- Multi-team trade support

### Matchup Simulation

- League-wide simulation in three modes:
  - Matchup results-based
  - Raw stat averages-based
  - Z-score-based

### Player Tools

- Full player pool with advanced metrics
- Free-agent filtering by position
- Side-by-side comparison (up to five players)
- Detailed player cards

## Tech Stack

- Backend: Python, FastAPI, Uvicorn
- Frontend: React (Vite), Axios, Recharts, Tailwind CSS
- Infrastructure: Docker, Docker Compose, Nginx
- Data source: ESPN Fantasy Basketball API (via authenticated cookies)

## Architecture

- `web/backend`: API endpoints, business logic orchestration, league data processing
- `core`: scoring logic, league configuration, ranking and Z-score calculations
- `web/frontend`: single-page application and data visualizations
- `nginx`: reverse-proxy configuration for containerized deployment

Data flow:

1. Frontend requests analytics via REST API.
2. Backend fetches league data from ESPN and applies calculations.
3. Processed metrics are returned to the frontend for interactive exploration.

## Getting Started

### Prerequisites

- Docker 20.10+ and Docker Compose 2.0+ (recommended)
- or Python 3.10+ and Node.js 18+ for local development
- Access to an ESPN Fantasy Basketball league

### Environment Variables

Create `.env` in the repository root:

```env
ESPN_S2=your_espn_s2_token_here
SWID={your-swid-guid-here}
```

How to obtain `ESPN_S2` and `SWID`:

1. Sign in to ESPN Fantasy Basketball.
2. Open browser developer tools.
3. Go to Application/Storage -> Cookies.
4. Copy `espn_s2` and `SWID` values.

### Run with Docker

- Windows: `docker-start.bat`
- Linux/macOS: `./docker-start.sh`
- Direct command: `docker-compose up -d`

App URLs:

- Frontend: `http://localhost:3001`
- Backend API: `http://localhost:8000`

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

- League ID and season year are configured in `core/config.py`.
- Frontend preferences are stored in browser `localStorage`.
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
- `admin`

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

## Limitations and Future Improvements

- ESPN private leagues require valid session cookies.
- Data freshness depends on ESPN API availability and league updates.
- Planned improvements include broader historical analysis and expanded scenario tooling.

## Contributing

Contributions, issue reports, and improvement ideas are welcome.

## License

This project is licensed under the MIT License. See `LICENSE` for details.
