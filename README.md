# Northstar Wealth

A local-first personal wealth-tracking prototype built with a React/TypeScript frontend, a Python API, and PostgreSQL. It separates liquid assets, savings, unvested compensation, forecast cash flows, and user-defined goals.

> **Demo-only warning:** The included portfolio, quotes, currency rates, cash flows, goals, vesting grants, and history are synthetic. No broker is connected, no market-data provider is configured, and the app has no authentication. Do not enter real financial data or expose this stack to the public internet.

## Stack decision

- **Backend:** Python 3.12, FastAPI, SQLAlchemy, Pydantic, and `Decimal` for financial calculations.
- **Database:** PostgreSQL 18. Transactions, account relationships, and exact decimal values fit a relational model; MongoDB is not needed for this application.
- **Frontend:** React 19, TypeScript, and Vite.
- **AI:** Optional read-only OpenAI API call using a key supplied for the current browser session. The app never stores the key or chat history.

For this personal MVP, Python makes the calculation and AI integration layers straightforward to change while keeping strict request validation and decimal financial arithmetic. For a large multi-team service, Java is also a strong choice. If starting that JVM service now, use **Java 25** as the current LTS when dependencies have verified support; Java 21 remains a mature, broadly compatible LTS baseline.

## Included in this first slice

- Responsive dashboard with separate tracked wealth, invested assets, cash, fixed deposits, and unvested compensation.
- Multi-currency EUR/USD display using an explicitly labelled synthetic FX rate.
- Sample holdings, deposit accrual, RSU vesting timeline, and projected cash-flow records.
- User-created goal templates, deadlines, priorities, risk preferences, and editable funding rules.
- One-time and recurring salary, bonus, bill, windfall, dividend, interest, and contribution forecasts.
- Priority-first, contribution-proportional, and fixed-percentage goal funding.
- Deterministic, buy-only asset-class allocation preview with reserve protection and a ten-minute preview expiry. It does not create cash flows or place trades.
- Read-only AI assistant that receives a compact portfolio snapshot only when the user submits a question.
- FastAPI Swagger UI at `/docs`.

## Not implemented yet

Broker/bank connectors, transaction imports and reconciliation, a balanced transaction ledger and tax lots, licensed live quotes, historical performance accounting, goal-to-position earmarking, instrument-level trade lists, automatic execution, user authentication, production schema migrations, and production-grade AI governance.

## Run locally

1. Install Docker Desktop and make sure its Linux engine is running.
2. Copy `.env.example` to `.env`; change the local database password if desired. The database is published to `localhost:55432` by default so it does not collide with an existing PostgreSQL server on port 5432. Change `POSTGRES_HOST_PORT` if that port is also occupied.
3. From the repository root, run:

   ```powershell
   docker compose up --build
   ```

4. Open [http://localhost:5173](http://localhost:5173) for the application and [http://localhost:8000/docs](http://localhost:8000/docs) for the API.

The database, API, and frontend ports are bound to `127.0.0.1`. The API creates the initial demo schema and seed data on startup. PostgreSQL 18 persists data in the named `postgres_data` Docker volume mounted at `/var/lib/postgresql`; PostgreSQL 18's official image stores its version-specific cluster below that path. The previous PostgreSQL 17 volume was verified empty before switching. Existing PostgreSQL 17 clusters must be migrated before reusing the data. To remove the **demo database volume** and its contents, stop the stack and explicitly run `docker compose down -v`.

### Run frontend without Docker

```powershell
cd frontend
npm install
npm run dev
```

The API and PostgreSQL services must still be running at `http://localhost:8000`.

### Run backend tests

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest
```

API tests use SQLite temporary databases; application configuration and the Docker stack use PostgreSQL.

## API overview

| Endpoint | Purpose |
|---|---|
| `GET /health` | Local API health |
| `GET /api/dashboard?currency=EUR` | Aggregated snapshot |
| `GET /api/goals` / `POST /api/goals` | List or add a goal |
| `PUT /api/goals/funding-shares` | Save fixed goal shares |
| `GET /api/policy` / `PUT /api/policy` | Read or update reserve, target mix, and funding rule |
| `GET /api/cash-flows?months=12` | Confirmed records and dated forecasts over a 1–24 month window |
| `GET` / `POST /api/cash-flow-schedules` | List or add one-time, monthly, quarterly, or annual forecasts |
| `DELETE /api/cash-flow-schedules/{id}` | Stop future projections without deleting the schedule record |
| `POST /api/recommendations/preview` | Generate a reproducible, non-executable cash-allocation preview |
| `POST /api/chat` | Send a read-only question with aggregate dashboard context |

Financial amounts use PostgreSQL `NUMERIC` and Python `Decimal`; the allocation code does not use binary floating-point calculations. Input target weights must sum to one, fixed goal shares must sum to 100%, and funding previews conserve the budget to the currency minor unit.

## AI key and privacy

The assistant accepts an OpenAI API key in the UI. The key is held in React component memory, placed in the `X-Provider-API-Key` request header, forwarded to the fixed OpenAI endpoint, and not persisted or logged by this prototype. Chat history lives only in the UI session. The submitted question and a compact snapshot of totals, allocation, goal progress, and data-quality warnings are sent to OpenAI. Provider charges are billed to the user's OpenAI account.

This is **not zero-knowledge processing**. Use only synthetic data here. A real deployment needs authenticated users, HTTPS, rate/cost limits, consent controls, strict secret-safe logging, data retention policy, and a reviewed AI provider integration. GitHub Copilot SDK is not currently wired into this initial slice.

## Financial and product boundaries

- Sample quotes are not live or executable prices. All market values and trends in the seeded profile are illustrative.
- Grant “after-tax” values are a simple user-editable-rate estimate, not jurisdictional tax advice. Option values use intrinsic value only.
- Goal progress is entered independently and is **not linked to positions**; it must not be interpreted as a reconciled account balance.
- Cash-flow schedules create dated forecasts only. They never confirm a receipt, change account balances, or become investable cash; occurrences are generated deterministically within the requested horizon.
- The prototype’s “unrealized gain” is based on sample average cost and current synthetic FX, not tax lots or historical acquisition FX.
- Allocation previews are asset-class-level, long-only, buy-only, and require user judgement. They do not select individual securities or submit orders.
- Do not use these calculations as personalized investment advice. Regulatory and tax treatment require jurisdiction-specific review before distribution.

## Production work required before real financial data

Implement tenant authentication and authorization, reviewed Alembic migrations, immutable balanced journal entries, duplicate-safe imports, broker connector permissions, provider licensing, historical price/FX provenance, tax-lot accounting, audit events, encrypted secrets, backup/restore procedures, AI consent and rate limits, and automated security testing. Disable seed data and enable migration-based deployment before production.