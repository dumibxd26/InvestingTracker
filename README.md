# Northstar Wealth

A local-first personal wealth tracker built with a React/TypeScript frontend, a Python API, and PostgreSQL. Each person registers a separate username/password application account, then adds the brokerage, bank, savings, and employer-plan accounts they want to track.

> **Local prototype:** Username/password authentication and user-level data separation are implemented. Optional provider-backed quotes are fetched only on explicit user actions. This is not a hardened public service: there is no password recovery, HTTPS reverse proxy, external security review, or broker connection. Keep it bound to your local machine and do not expose it to the public internet.

## Stack decision

- **Backend:** Python 3.12, FastAPI, SQLAlchemy, Pydantic, and `Decimal` for financial calculations.
- **Database:** PostgreSQL 18. Transactions, account relationships, and exact decimal values fit a relational model; MongoDB is not needed for this application.
- **Frontend:** React 19, TypeScript, and Vite.
- **Authentication:** Username/password registration and login, Argon2id password hashes, hashed bearer-session tokens, and API-level tenant filtering.
- **AI:** Optional read-only OpenAI-compatible request using a key supplied for the current browser session. The app never stores the provider key or chat history.
- **Appearance:** Light/dark theme switch, remembered in this browser.

For this personal MVP, Python makes the calculation and AI integration layers straightforward to change while keeping strict request validation and decimal financial arithmetic. For a large multi-team service, Java is also a strong choice. If starting that JVM service now, use **Java 25** as the current LTS when dependencies have verified support; Java 21 remains a mature, broadly compatible LTS baseline.

## Included in this first slice

- Username/password application account creation, sign-in/out, and per-user portfolios.
- Blank personal workspaces with profile-specific display name, base currency, and cached provider FX rates or an optional manual USD-per-EUR reference.
- Responsive dashboard with separate tracked wealth, invested assets, cash, fixed deposits, and unvested compensation.
- Manually managed brokerage, bank, savings, and employer-plan account registry; opening cash persists in PostgreSQL.
- Provider-backed stock/ETF search and holdings entry; manually refreshable Twelve Data quotes and EUR/USD, EUR/RON, and USD/RON FX rates. Automatic hourly refresh is disabled.
- User-created goals where the user supplies the purpose, currency, amount, priority, risk comfort, deadline flexibility, and contribution plan.
- One-time and recurring salary, bonus, bill, windfall, dividend, interest, and contribution forecasts.
- One-time “extra cash received” entries that update the selected owned cash account and are protected against duplicate retries.
- Priority-first, contribution-proportional, and fixed-percentage goal funding.
- No allocation rule or asset target weights are preloaded; the user must set them before generating an investment preview.
- Deterministic, buy-only asset-class allocation preview with reserve protection and a ten-minute preview expiry. It does not create cash flows or place trades.
- Read-only AI assistant that receives a compact portfolio snapshot only when the user submits a question.
- Dark mode with the selected preference saved in the browser.
- FastAPI Swagger UI at `/docs`.

## Market data setup

Set `TWELVE_DATA_API_KEY` in `.env` to enable symbol search and refresh. The key is passed to the backend only; it is never sent to the browser. No scheduled or hourly market-data job runs. A manual refresh updates current held symbols and the three supported FX pairs.

Twelve Data is the initial provider adapter because it covers symbol discovery, quotes, and FX. Its current plan page describes the free Basic allowance as non-display, while an Individual Grow subscription (listed at $29/month when this integration was designed) permits internal personal-dashboard display. Check current price, market coverage, latency, and display rights before use: [Twelve Data pricing](https://twelvedata.com/pricing). Provider timestamps are shown in the UI and plan-specific delay may apply; this application does not claim every listing is real-time.

Broker/bank connectors, transaction imports and reconciliation, a balanced accounting ledger and tax lots, historical TWR/IRR accounting, goal-to-position earmarking, instrument-level buy lists, automatic execution, password recovery/MFA, and production operational controls are not implemented.

## Run locally

1. Install Docker Desktop and make sure its Linux engine is running.
2. Copy `.env.example` to `.env`. Set a unique, random PostgreSQL password; configure `AI_MODEL` for chat and `TWELVE_DATA_API_KEY` for stock search and manual market-data refresh. The database is published to `localhost:55432` by default so it does not collide with another PostgreSQL server on port 5432; change `POSTGRES_HOST_PORT` if needed.
3. From the repository root, run:

   ```powershell
   docker compose up --build
   ```

4. Open [http://localhost:5173](http://localhost:5173) for the application and [http://localhost:8000/docs](http://localhost:8000/docs) for the API.

The database, API, and frontend ports are bound to `127.0.0.1`. Alembic applies versioned schema migrations before the API starts. PostgreSQL 18 persists data in the named `postgres_data` volume mounted at `/var/lib/postgresql`. Application users, account records, profile settings, goals, and cash flows survive `docker compose restart`, container recreation, and `docker compose down` followed by `docker compose up`. `docker compose down -v` deliberately deletes the database volume and all stored data.

Do not wipe the existing volume. Existing records from the earlier shared sample/demo profile are preserved in the database but are no longer exposed through authenticated application APIs. They are not assigned automatically to the first registered person, which avoids exposing one person's legacy records to another. New registrations start with a blank portfolio.

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

API tests use isolated SQLite temporary databases; the Docker stack uses PostgreSQL and Alembic migrations.

## API overview

| Endpoint | Purpose |
|---|---|
| `GET /health` | Local API health |
| `POST /api/auth/register` / `POST /api/auth/login` | Create an application login or sign in |
| `POST /api/auth/logout` / `GET /api/auth/me` | Revoke current session or get the signed-in profile |
| `GET /api/profile` / `PUT /api/profile` | Read or update display name, base currency, and optional manual FX reference |
| `GET /api/dashboard?currency=EUR` | Signed-in user's aggregated snapshot |
| `GET /api/accounts` / `POST /api/accounts` | List or add the signed-in user's manual financial accounts |
| `GET /api/market/status` | Check whether provider-backed market data is configured |
| `GET /api/market/search?q=MSFT` | Search provider listings for stocks and ETFs |
| `POST /api/holdings` | Add a selected stock/ETF listing and record its initial quote |
| `POST /api/market/refresh` | Manually refresh held symbols and EUR/USD/RON FX rates |
| `GET /api/goals` / `POST /api/goals` | List or add a goal |
| `PUT /api/goals/funding-shares` | Save fixed goal shares |
| `GET /api/policy` / `PUT /api/policy` | Read or update reserve, target mix, and funding rule |
| `GET /api/cash-flows?months=12` | Confirmed records and dated forecasts over a 1–24 month window |
| `POST /api/cash-flows/extra-cash` | Record actual extra cash against one of the user's liquid accounts |
| `GET` / `POST /api/cash-flow-schedules` | List or add one-time, monthly, quarterly, or annual forecasts |
| `DELETE /api/cash-flow-schedules/{id}` | Stop future projections without deleting the schedule record |
| `POST /api/recommendations/preview` | Generate a reproducible, non-executable cash-allocation preview |
| `POST /api/chat` | Send a read-only question with aggregate dashboard context |

Financial amounts use PostgreSQL `NUMERIC` and Python `Decimal`; the allocation code does not use binary floating-point calculations. Input target weights must sum to one, fixed goal shares must sum to 100%, and funding previews conserve the budget to the currency minor unit.

## AI key and privacy

The assistant accepts an OpenAI API key in the UI. The key is held in React component memory, placed in the `X-Provider-API-Key` request header, forwarded to the fixed OpenAI endpoint, and not persisted or logged by this prototype. Chat history lives only in the UI session. The submitted question and a compact snapshot of totals, allocation, goal progress, the 50 largest tracked holdings, quote timestamps, cached FX rates, and data-quality warnings are sent to OpenAI. Provider charges are billed to the user's OpenAI account.

This is **not zero-knowledge processing**. AI use is optional. A model name must be configured via `AI_MODEL`; each person supplies their provider key in the browser for that session.

## Authentication and local security

- Usernames are normalized to lowercase and must be unique; registration requires a password of at least 12 characters.
- Passwords are hashed with Argon2id. The server stores only a SHA-256 digest of each randomly generated bearer-session token.
- Sessions expire after 30 days. Signing out revokes the active session.
- The token is held in browser `sessionStorage`, sent over the local API's `Authorization: Bearer` header, and cleared on sign-out/session expiry. Account API reads and writes are filtered by the verified session's user ID.
- New profiles contain no demo accounts, balances, holdings, goals, cash-flow records, or seeded FX rate. User selects their base currency. Cross-currency totals require a cached market-data FX rate or a manually supplied USD-per-EUR reference.
- There is no password reset or recovery workflow; forgetting the password currently means losing access to that application profile. Back up the PostgreSQL volume.

The default Compose port bindings are loopback-only. Do not expose this service to another machine or the internet: it currently has no TLS, login rate limiting, MFA, breach monitoring, recovery flow, or external security review. Set a strong, unique database password in `.env` even for local use.

## Financial and product boundaries

- The application no longer seeds demo users or sample financial records. Historical sample rows from an older shared profile are preserved but inaccessible through the new user-scoped APIs.
- New profiles start without a funding rule, asset-class weights, reserve target, balances, or goals; the user chooses these before an allocation preview is enabled.
- Provider quotes are informational marks and may be delayed according to the selected provider plan and listing. Quotes and FX update only after a manual refresh; there is no automatic hourly job. They are not executable prices.
- Grant “after-tax” values are a simple user-editable-rate estimate, not jurisdictional tax advice. Option values use intrinsic value only.
- Goal progress is entered independently and is **not linked to positions**; it must not be interpreted as a reconciled account balance.
- Cash-flow schedules create dated forecasts only. They never confirm a receipt, change account balances, or become investable cash; occurrences are generated deterministically within the requested horizon.
- Manual account creation stores account metadata and opening cash directly, not as a complete double-entry transaction ledger. It does not connect to the institution or import holdings.
- Recording extra received cash atomically increments the selected liquid account and creates a confirmed cash-flow record. It is a cash receipt, not broker reconciliation.
- The prototype’s “unrealized gain” uses one average-cost figure and the latest cached quote/FX mark, not tax lots or historical acquisition FX.
- Allocation previews are asset-class-level, long-only, buy-only, and require user judgement. They do not select individual securities or submit orders.
- Do not use these calculations as personalized investment advice. Regulatory and tax treatment require jurisdiction-specific review before distribution.

## Production work required before real financial data

Before distributing beyond local personal use, obtain an independent security review; add HTTPS, login rate limiting/MFA, password recovery, monitoring, backup/restore procedures, immutable balanced journal entries, duplicate-safe imports, broker connector permissions, provider licensing, historical price/FX provenance, tax-lot accounting, audit events, AI consent/rate limits, and production operational controls.