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
- Manually managed brokerage, bank, savings, and employer-plan account registry; opening cash persists in PostgreSQL as the initial currency sub-account balance.
- Multi-currency EUR/USD/RON cash sub-accounts under each bank or broker. Existing account currency and opening cash are migrated into its primary sub-account.
- Guided initial portfolio setup to enter multiple institutions and current currency balances plus already-owned stock/ETF positions in one atomic save. Average cost defaults to the instrument's listing currency and can be overridden.
- Provider-backed stock/ETF search and holdings entry; manually refreshable Twelve Data quotes and EUR/USD, EUR/RON, and USD/RON FX rates. Automatic hourly refresh is disabled.
- User-created goals where the user supplies the purpose, currency, amount, priority, risk comfort, deadline flexibility, and contribution plan; active goals can be edited or archived from Goals & plan.
- One-time and recurring salary, bonus, bill, windfall, dividend, interest, and contribution forecasts.
- One-time “extra cash received” entries that update the selected owned currency sub-account and are protected against duplicate retries.
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
| `POST /api/accounts/{id}/subaccounts` | Add a EUR, USD, or RON cash sub-account to an institution |
| `POST /api/portfolio/initialize` | Atomically initialize institutions and current currency balances plus already-owned stock/ETF positions without charging their costs again |
| `DELETE /api/accounts/{id}` | Remove an account and its balance/assets from the tracker while preserving linked cash-flow history |
| `GET /api/market/status` | Check whether provider-backed market data is configured |
| `GET /api/market/search?q=MSFT` | Search provider listings for stocks and ETFs |
| `POST /api/holdings` | Add a selected stock/ETF listing, record its quote, and convert/debit the purchase cost from the chosen EUR/USD/RON sub-account |
| `PUT /api/holdings/{id}` / `DELETE /api/holdings/{id}` | Update a position and apply the converted cost-basis difference, or remove it and restore its recorded funding-currency cost |
| `POST /api/holdings/{id}/sell` | Record a sale of all or part of a position at a user-entered after-tax price per unit in the holding's currency; credits proceeds to that currency's wallet in the same account (idempotent via `idempotency_key`; employer-plan holdings cannot be sold) |
| `POST /api/holdings/{id}/transfer` | Move all or part of a position to another account the user owns; merges into an existing position of the same instrument there. An optional fiat fee can be deducted from the source or destination wallet. No cash moves for the shares. Holdings linked to a goal cannot be moved (idempotent via `idempotency_key`; employer-plan holdings cannot be moved) |
| `POST /api/cash-transfers` | Move cash between two of the user's wallets (for example XTB EUR to ING RON); same-currency transfers move the same amount, cross-currency transfers take a user-entered received amount with no automatic FX. An optional fiat fee can be deducted from the source or destination wallet. No trade or cash-flow record is created. Idempotent via `idempotency_key`; employer-plan wallets are not allowed |
| `POST /api/market/refresh` | Manually refresh held symbols and EUR/USD/RON FX rates |
| `GET /api/projections/portfolio?target_date=2036-10-11` | Deterministic editable-return projection for current account assets; excludes forecasts and unvested awards |
| `GET /api/goals` / `POST /api/goals` | List or add a goal |
| `PUT /api/goals/{id}` / `DELETE /api/goals/{id}` | Update a goal or archive it from the active plan |
| `POST /api/deposits` / `DELETE /api/deposits/{id}` | Create a bank/savings term deposit funded from a selected currency wallet, or remove it and restore principal |
| `PUT /api/goals/funding-shares` | Save fixed goal shares |
| `GET /api/policy` / `PUT /api/policy` | Read or update reserve, target mix, and funding rule |
| `GET /api/cash-flows?months=12` | Confirmed records and dated forecasts over a 1–24 month window |
| `POST /api/accounts` / `POST /api/accounts/{id}/subaccounts` | Create an account or a currency wallet; bank/savings wallets accept an optional annual interest rate and start date |
| `PUT /api/accounts/{id}/subaccounts/{wallet_id}/interest` | Set or clear a bank/savings wallet's yearly rate (credited monthly) |
| `POST /api/stock-purchase-plans` / `DELETE /api/stock-purchase-plans/{id}` | Plan or remove a discounted share purchase (discount, tax when received, tax on later profit) |
| `POST /api/cash-flows/extra-cash` | Record actual extra cash (for example a bonus) against one of the user's liquid accounts |
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

- Account-to-account transfers (for example XTB to ING) only move `cash_balance` between two existing wallets. They create no trades and no `CashFlow` rows. They are reserved as the base for future spending links. An optional fiat fee (for example a wire fee or tax) can be deducted from either the source or the destination wallet, in that wallet's currency; there is no automatic FX on fees.
- Stock transfers move a holding between two accounts the user owns, with no cash movement for the shares. A full move removes the source position; a partial move prorates the funding cost. The destination merges with an existing position of the same instrument, using a weighted-average cost and the earliest purchase date. Moved positions keep no funding wallet link. Holdings linked to a goal must be unlinked first.
- The application no longer seeds demo users or sample financial records. Historical sample rows from an older shared profile are preserved but inaccessible through the new user-scoped APIs.
- The Overview investment treemap groups identical normalized ticker symbols across accounts/listings, sizes each tile by its combined estimated after-tax market value, and colors it by its combined estimated after-tax gain/loss percentage. Existing holdings are backfilled at a 5% nominal return assumption; new ETFs default to X/6% and individual stocks to Y/5%. Users can edit risk tier and return per holding. These starting values are placeholders, not provider-derived ratings or expected performance.
- Portfolio projections apply each holding's user-entered effective annual total-return assumption, hold current FX constant, keep ordinary cash flat (except savings wallets with a monthly interest rate), and accrue deposits only to maturity (without assuming reinvestment). They exclude unvested awards, future cash flows and additional contributions. The risk tiers are qualitative labels, not historical volatility or probability-of-loss estimates; no crypto instrument type or historical volatility analysis is implemented yet. Projection results are not promises or investment advice.
- New profiles start without a funding rule, asset-class weights, reserve target, balances, or goals; the user chooses these before an allocation preview is enabled.
- Provider quotes are informational marks and may be delayed according to the selected provider plan and listing. Quotes are fetched on explicit symbol search/add and manual refresh; FX and existing quote marks do not refresh automatically. They are not executable prices.
- The Overview breaks wealth down by account: tracked cash, gross owned holdings, estimated tax on gains, after-tax holdings, fixed-deposit accrual, and account total. The account total excludes unvested awards and future income; those remain separate.
- User-entered named RSU/option awards support either generated duration/cliff/interval schedules or custom date-and-share tranches; custom awards can omit an unknown original grant date. Unvested value uses the latest cached quote (RSUs: unvested units × quote; options: unvested units × max(quote − strike, 0)); manually refresh quotes to update marks. Tranches whose availability date has passed are treated as vested and stop contributing to unvested value. Unvested awards are excluded from total tracked wealth and shown separately; future salary/bonus forecasts are also excluded until credited as tracked cash. These estimates are not owned-share balances or P&L.
- Grant tax-at-vest assumptions are separate from configurable short-/long-term sale-tax scenarios. Sale scenarios apply simple percentage haircuts to modeled stock value; they do not calculate taxable capital gains. These are user assumptions, not jurisdictional tax advice. Option values use intrinsic value only.
- Goals can virtually earmark selected stocks/ETFs and fixed deposits after linking their parent accounts. Assigned assets contribute their current after-tax holding value or accrued deposit value to goal progress without moving money or duplicating account wealth. An asset can be assigned to only one active goal. Tracked cash remains unassigned. Optional monthly/yearly goal budgets are stored for visualization only and do not post money or affect cash-routing rules.
- Fixed deposits are created from a selected bank/savings currency wallet, which is debited by the principal; maturity and accrued interest are estimated from the start date, term, annual rate, and capitalization choice. Deleting a deposit restores principal only; it does not credit estimated interest.
- Economy (savings) wallets can carry a yearly interest rate. One twelfth of it is credited to the wallet balance once a month on the start date's day of the month, so interest compounds monthly. Credits are confirmed `interest` cash flows, are posted when the app loads (missed months after the start date are caught up once, up to 50 years) and are idempotent per wallet and date. Catch-up uses the wallet's current balance, interest is gross of any tax, and nothing is read from your bank. Portfolio projections compound these wallets monthly.
- When adding a bank account with an interest rate, choose where interest is paid: the bank account itself (Salt, XTB style, one account), or a separate interest account (ING, BT style). The separate option creates a savings account in the same currency that starts at 0, while the spending bank account earns no interest. Money is moved into the interest account with Add funds.
- Discounted share purchase plans (for example an employer ESPP) store the stock, shares, purchase date, discount, the tax when received (default 45%, applied to the discount as salary-style income) and the tax on later profit (default 10%). On the purchase date, if the paying wallet has enough cash, the discounted price plus the tax when received is deducted once, and the shares are added to the chosen brokerage/employer-plan account with the market price that day as cost basis; the 10% (or chosen) rate then replaces the default 3% for those shares (blended by quantity if merged into an existing position). Until then the plan is excluded from wealth and projections. If cash or a price is missing, the plan stays scheduled with a warning. These are the user's own assumptions, not tax advice.
- Cash-flow schedules create dated forecasts unless salary or bonus is explicitly set to auto-post to a selected liquid account and currency wallet. Due auto-posts are idempotent and update Northstar's tracked cash balance the next time the dashboard or cash-flow ledger refreshes on or after the scheduled date; missed dates are caught up. This is bookkeeping only—not a bank transfer or payroll confirmation. Variable or uncertain bonuses should remain forecast-only until known.
- Manual account creation stores institution metadata and sub-account balances directly, not as a complete double-entry transaction ledger. It does not connect to the institution or import holdings.
- Removing a manual account from the tracker deletes its linked holdings and fixed deposits, removes its tracked cash balance, stops its active auto-post schedules, and preserves cash-flow history with the account link cleared. It does not close or modify any real bank or broker account.
- Recording a sale is bookkeeping only: it does not place a trade. The user enters the after-tax price per unit; proceeds are credited to the same account's wallet in the holding's currency (created if missing), and the sold units are removed from the position. Sales are kept as history and do not write a cash-flow row.
- Adding a stock/ETF models a local purchase: `quantity × average_cost` in the listing currency is converted using available FX and debited from the user-selected EUR/USD/RON broker sub-account. The tracker records the actual funding-currency amount for later edits/removal and refuses purchases with insufficient cash. This changes only Northstar's records; it does not submit a trade to a broker.
- Recording extra received cash atomically increments the selected liquid account and creates a confirmed cash-flow record. It is a cash receipt, not broker reconciliation.
- The prototype does not calculate realized P&L or tax lots. The heatmap's estimated gain/loss is a mark-to-average-cost comparison using current quotes, with the 3% positive-gain tax estimate applied; it is not a realized return or tax statement.
- Positions store one average purchase date and average cost; older holdings are assumed purchased on 2025-01-01 unless edited. The displayed estimated after-tax position value subtracts 3% of positive market gain over average cost. This is an illustrative haircut, not realized P&L, lot-level accounting, or tax advice. Separate MSFT grant sale-rate scenarios use the grant date, the stated short-/long-term holding period, and the grant-specific percentages.
- Allocation previews are asset-class-level, long-only, buy-only, and require user judgement. They do not select individual securities or submit orders.
- Do not use these calculations as personalized investment advice. Regulatory and tax treatment require jurisdiction-specific review before distribution.

## Production work required before real financial data

Before distributing beyond local personal use, obtain an independent security review; add HTTPS, login rate limiting/MFA, password recovery, monitoring, backup/restore procedures, immutable balanced journal entries, duplicate-safe imports, broker connector permissions, provider licensing, historical price/FX provenance, tax-lot accounting, audit events, AI consent/rate limits, and production operational controls.