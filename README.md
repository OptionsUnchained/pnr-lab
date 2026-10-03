# Expected Move Discord Bot

An original Discord app that recreates the expected-move functionality shown in your screenshot. You own the Discord application and control the code, credentials, channels, and hosting.

## What it does

Use this slash command in Discord:

```text
/expected-move ticker:CRWD
```

Use `/epr ticker:QQQ` to retrieve Tastytrade's account-specific Expected Price
Range before opening a position. The bot first checks current capital
requirements and, when the symbol is not already present, submits a read-only
margin dry run for one share. It displays the downside and upside EPR returned
by Tastytrade; it does not place or route an order. EPR is available only when
the selected Tastytrade account and OAuth grant expose portfolio-margin data.
The EPR module has an explicit endpoint guard: its only POST target is
`/margin/accounts/{account}/dry-run`, and it rejects any path containing an
order-submission route.

Use `/epr-wl` to retrieve EPR for every symbol in the earnings watchlist plus
`SPY`, `QQQ`, and `SMH` in one alphabetical, one-row-per-ticker report. When
`DATABASE_URL` is configured, the command saves one observation
per symbol per day and displays changes in downside and upside EPR magnitude
versus the most recent prior collection. A positive change means that side of
the EPR widened; a negative change means it narrowed. When `EPR_CHANNEL_ID` is
set, the same report posts automatically at 6:31 AM Pacific every weekday.
The first saved report establishes the baseline, so changes appear beginning
with the next collection.

The bot also provides `/market-movers`, which ranks the top 15 gainers and
losers among active, non-ETF companies with a Tastytrade market cap of at
least $20 billion. The command offers three report choices: Premarket compares
the last actual premarket trade with the prior regular close; Regular
Session compares the latest regular trade with the prior close; After Market
compares the last actual after-hours trade with today's regular close. Regular
Session is the manual-command default.

When `MOVERS_CHANNEL_ID` is configured, the bot automatically posts on weekdays
at these Pacific times:

- 6:15 AM: Premarket
- 6:45 AM, 8:00 AM, 11:00 AM, and 12:30 PM: Regular Session
- 1:30 PM: After Market

Pacific daylight-saving changes are handled automatically. Movers are rendered
as a compact mobile-friendly image with side-by-side gainers and losers and
green/red percentage changes.

Use `/earnings` for a market-cap-ordered earnings tracker covering the configured
stock watchlist. It shows market capitalization, the expected report date,
calendar days remaining, and a check mark when Tastytrade marks the date as
confirmed rather than estimated. A red `❗️` marks reports fewer than 22 days
away, while `‼️` marks reports fewer than 12 days away. If Tastytrade supplies
no upcoming date, the
bot compares the same-quarter date from the prior year plus 364 days with the
recent median quarterly interval. It uses that estimate when the methods agree
within seven days. If the strict comparison cannot be completed, it falls back
to the most recent prior earnings report plus 89 days, provided that date is
still in the future. All historical estimates display a `~`; otherwise the date
is reported as unavailable.

Use `/earnings-lee` for the same live earnings data in the original proportional
text layout: bold ticker, status symbols, dollar-denominated market cap, full
date, and written countdown separated by bullets. The aligned `/earnings`
command remains unchanged.

Use `/gex ticker:IWM` to generate a dark, mobile-friendly gamma-exposure chart
by expiration. Add an expiration, such as
`/gex ticker:OKTA expiration:2026-10-16`, to chart GEX by strike for that
regular monthly expiration. Discord autocompletes the available monthlies after
the ticker is entered. Both chart types show the next earnings date beneath the
company name using the same confirmed/estimated/historical fallback hierarchy
as `/earnings`; confirmed dates carry a check mark, historical estimates carry
`~`, and the calendar DTE is included. Strike-chart titles also show the DTE of
the selected option expiration.

The GEX calculation is the conventional dealer-positioning proxy:

```text
Contract GEX = Gamma × Open Interest × Contract Multiplier × Price² × 1%
Call GEX     = positive
Put GEX      = negative
```

Both GEX charts display a bias percentage beneath total GEX:

```text
GEX bias = Net GEX ÷ (Total call GEX + absolute total put GEX)
```

The on-chart reference classifies an absolute bias below 10% as balanced,
10–30% as slight, 30–60% as moderate, and 60% or more as strong. Direction is
based on the sign of net GEX.

The strike chart reads the complete selected expiration before trimming the
display. It always retains the core strikes around spot, the global leaders by
open interest, and the global leaders by absolute GEX. This prevents an
isolated high-open-interest strike from being lost after a long run of empty
strikes. The expiry overview uses up to 36 representative expirations and the
120 strikes nearest spot per expiration to keep the on-demand chart responsive.
Every displayed expiration has its own x-axis label and a faint vertical guide
through the center of its call/put bar pair. Labels automatically shrink and
rotate as the chart becomes denser.

When `DATABASE_URL` is configured, the bot also records daily GEX history at
6:45 AM Pacific on weekdays for the symbols in `GEX_HISTORY_SYMBOLS` and the
fixed monthlies in `GEX_HISTORY_EXPIRATIONS`. It stores one normalized summary
row plus complete strike-level rows for every ticker/expiration/day. The
summary includes total call and put GEX, net and gross GEX, bias, the three
largest call walls, the three largest put walls, spot price, DTE, and collection
coverage. `/gex-history` returns a compact daily table. Running `/gex` manually
for a tracked ticker and expiration seeds that day only when no observation has
already been saved, so it cannot overwrite the standardized scheduled capture.
When `GEX_HISTORY_CHANNEL_ID` is set, the same 6:45 AM collection posts one
compact Discord confirmation. It lists every tracked ticker beneath each
expiration with its bias and contract coverage, using complete, partial, and
failed status markers. The collection still runs and saves normally when this
channel variable is omitted.

Use `/options-flow ticker:NVDA expiration:2026-11-20` to select a regular
monthly expiration and rank its 10 busiest strikes by combined call-and-put
contract volume for the latest session. The image also shows call and put
ask-side/bid-side volume, volume/open-interest, estimated premium, unclassified
volume coverage, and an aggressor-flow bias. Ask-side and bid-side volume are
directional estimates only: they do not identify opening versus closing trades,
and multi-leg orders can make a single-leg reading misleading.

Premarket and after-market movers use Tastytrade's last Trade event only when
it is explicitly flagged as extended-hours and timestamped inside the selected
session. Premarket compares that trade with the prior close; after-market
compares it with that day's regular-session close. Symbols without a trade in
the applicable extended session are excluded rather than assigned a midpoint
or stale regular-session price.

The bot returns:

- live bid/ask midpoint from Tastytrade's DXLink feed;
- Tastytrade 30-day implied volatility (IVx) and IV rank;
- the earliest upcoming regular monthly expiration and the following four monthlies;
- Tastytrade high, low, and dollar move for each expiration, derived from live option marks.

The calculation matches Tastytrade's chain-style expected move:

```text
Expected move = 60% × ATM straddle
              + 30% × first OTM strangle
              + 10% × second OTM strangle
High = Price + expected move
Low  = Price − expected move
```

Formula reference: <https://support.tastytrade.com/support/s/solutions/articles/43000435415>

This is a statistical estimate, not a guarantee or a trade recommendation.

## 1. Create your Discord application

1. Open <https://discord.com/developers/applications> and choose **New Application**.
2. Name it, for example, **Soteria Options Bot**.
3. Open **Bot**, create the bot if prompted, and select **Reset Token**. Copy the token into a secure password manager. This becomes `DISCORD_TOKEN`.
4. You do **not** need the privileged Message Content intent.
5. Open **Installation** (or **OAuth2 → URL Generator**, depending on the portal layout).
6. Enable the `applications.commands` and `bot` scopes.
7. Grant only **View Channels**, **Send Messages**, **Embed Links**, and **Use Application Commands**. Administrator is unnecessary.
8. Open the generated installation URL, choose your server, and authorize the app.

For immediate command registration during setup, enable Developer Mode in Discord, copy your server ID, and use it as `DISCORD_GUILD_ID`. If you omit it, the command is registered globally and may take longer to appear.

## 2. Create Tastytrade API credentials

The current Tastytrade Python SDK uses an OAuth provider secret and refresh token. Obtain them through Tastytrade's developer/OAuth flow and store them as `TT_SECRET` and `TT_REFRESH`.

Official references:

- Tastytrade API: <https://developer.tastytrade.com/>
- Python client: <https://github.com/tastyware/tastytrade>
- Market-metrics endpoint: <https://developer.tastytrade.com/reference/market-metrics/getMarketMetricsIndex>

The bot is read-only: it requests quotes, volatility metrics, option-chain
metadata, capital requirements, and margin dry runs. It contains no
order-submission code.

## 3. Run locally

Install Python 3.12 or newer, then from this folder:

```bash
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
# macOS/Linux
source .venv/bin/activate
```

Install and configure:

```bash
pip install .
cp .env.example .env
```

Windows users can copy `.env.example` to `.env` in File Explorer. Fill in the values, then load them through your terminal or use Docker/cloud environment variables. The application reads environment variables directly; it intentionally does not load `.env` automatically in production.

Example for PowerShell:

```powershell
$env:DISCORD_TOKEN="your_discord_token"
$env:DISCORD_GUILD_ID="your_server_id"
$env:MOVERS_CHANNEL_ID="your_destination_channel_id"
$env:TT_SECRET="your_tastytrade_provider_secret"
$env:TT_REFRESH="your_tastytrade_refresh_token"
$env:TT_ACCOUNT_NUMBER="your_portfolio_margin_account_number"
python -m expected_move_bot
```

## 4. Run with Docker

Build:

```bash
docker build -t expected-move-bot .
```

Run using a local `.env` file:

```bash
docker run --env-file .env --restart unless-stopped expected-move-bot
```

## 5. Deploy to Railway

1. Put this project in a private GitHub repository.
2. Create a Railway project and deploy from that repository.
3. Add `DISCORD_TOKEN`, `DISCORD_GUILD_ID`, `TT_SECRET`, `TT_REFRESH`, and
   `MOVERS_CHANNEL_ID` under Railway variables. Add `TT_ACCOUNT_NUMBER` when
   the OAuth login has multiple accounts; select the portfolio-margin account.
4. In the same Railway project, choose **New → Database → PostgreSQL**. In the
   bot service variables, add `DATABASE_URL=${{Postgres.DATABASE_URL}}` (use the
   actual database-service name if Railway named it differently).
5. Optionally add `GEX_HISTORY_SYMBOLS` and `GEX_HISTORY_EXPIRATIONS`. The
   defaults are the eight requested stocks and the Nov. 20/Dec. 18, 2026
   monthlies.
6. To receive the daily collection confirmation, create a Discord channel,
   copy its channel ID, and add it as `GEX_HISTORY_CHANNEL_ID` in Railway.
7. Create or select the Discord channel for the daily EPR watchlist, copy its
   channel ID, and add it as `EPR_CHANNEL_ID`. The report posts there at 6:31
   AM Pacific on weekdays.
8. Railway detects the included Dockerfile and starts the worker. The bot
   creates its GEX and EPR history tables automatically; no manual SQL is needed.
9. Check the deployment logs for command synchronization and `GEX history
   enabled`, then try `/gex-history` in Discord. It will fill after the first
   6:45 AM PT capture; running a matching `/gex` command saves the current day
   immediately. The scheduled collection report posts after the pull finishes.
   Run `/epr-wl` once to verify the full EPR report and establish its first
   comparison baseline.

Do not commit `.env`, tokens, passwords, or OAuth secrets. If a token is ever exposed, rotate it immediately.

## Test the calculations

```bash
pip install ".[dev]"
pytest -q
ruff check .
```

The unit tests require no Tastytrade or Discord credentials.

## Practical notes

- The displayed current price and option marks are live bid/ask midpoints, so they can differ slightly from the last traded prices shown elsewhere.
- Outside regular hours, wide or stale bid/ask quotes can make the estimate less representative.
- The bot deliberately excludes weeklies and displays five consecutive regular monthly expirations, starting with the earliest upcoming monthly.
- Tastytrade controls API availability and market-data entitlements.
- IVx is shown for context. Each expiration's expected move uses its ATM straddle and the first two OTM strangles.
- Movers use the latest extended-hours trade versus the previous regular-session close.
- Scheduled reports do not post on weekends. On exchange holidays, the current-session check prevents a stale report.
- GEX uses live Tastytrade gamma with the latest available open interest. Open
  interest normally updates daily, and actual dealer positioning is not public,
  so the chart is an estimate rather than a confirmed inventory measure.
