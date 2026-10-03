# PNR Lab

A portfolio scenario calculator for GitHub Pages. Enter an original portfolio and a proposed portfolio, then compare modeled upside/downside point of no return (PNR), account equity, EPR stress losses, and each leg's contribution. Pricing is dependency-free; optional screenshot OCR loads Tesseract.js in the browser.

## Open immediately

Open `index.html` in a browser. It includes the app's scripts and styles. No installation, API key, brokerage login, server, or build is required for the calculator. Screenshot OCR requires internet access and a browser supporting WebAssembly/web workers; use GitHub Pages over HTTPS for the best compatibility. Browser-local storage saves inputs when supported; JSON export/import transfers projects between devices.

The application starts with blank position tables. “Load sample data” uses a synthetic `XYZ` portfolio with round-number assumptions. No user holdings, account values, screenshots or broker observations are bundled. Your entered positions are stored only in your browser. Do not commit exported personal input JSON to a public repository.

## Host on GitHub Pages

1. Create a GitHub repository, for example `pnr-lab`. On GitHub Free, use a public repository for Pages.
2. Upload the contents of this folder to the repository root. `index.html` must be at the root, not inside another nested `pnr-lab` directory. You can alternatively upload only `index.html` and `.nojekyll`.
3. Open repository **Settings → Pages**.
4. Under **Build and deployment**, choose **Deploy from a branch**.
5. Select **main** and **/(root)**, then **Save**.
6. GitHub supplies the site URL, typically `https://YOUR-USERNAME.github.io/pnr-lab/`. Publication can take several minutes.

GitHub Pages sites are ordinarily public even when the source repository is private. This application has no brokerage connection or analytics. Its source and bundled example are public; browser-local portfolios are not part of the deployed files. Screenshot OCR loads Tesseract.js 6.0.1 and core 6.0.0, worker code and English model files from public CDNs on first use. Images are passed to a local browser worker, not uploaded to an OCR service. CDN files may be cached; internet access is required for initial loading. If loading fails, the text fallback and manual entry remain available.

## Screenshot import

1. Set the snapshot date to the date of your screenshot. This is used to infer missing expiration years.
2. In **Screenshot import**, choose a photo, take one with your phone, paste an image, or drag and drop it. The browser accepts any image format it can decode; if a HEIC image cannot be decoded, export it as JPEG or PNG. Supported layout is a tastytrade positions list like the mobile view, showing a left quantity, month/day date, strike/P or C below it, and price columns on the right. Auto detection distinguishes bid/ask from P/L / Last / Trade Price views. In P/L views, it extracts Last and entry prices for reference and leaves current marks blank. To deliberately use Last as a current-price proxy, select **Use Last as proxy (may be stale)** before reading the image. This is not a bid/ask midpoint. Capital Requirements screens and order tickets are excluded from holdings extraction. Crop to that list for better results. Option-chain screenshots and multi-leg order/roll tickets do not establish holdings and are not automatically supported.
3. Choose **Original positions** or **Proposed positions**, and replace or append.
4. Select **Read selected image**. Grayscale, dark-background inversion and contrast preprocessing are applied before browser-local OCR.
5. Compare the review table against the image. Correct dates, quantities and minus signs, strikes, bid/ask, and midpoint. The midpoint updates when bid or ask is edited. Quantity signs that are not clearly detected are left blank. Long quantities may need manual entry because OCR cannot establish their sign reliably.
6. Confirm each row. Missing/invalid fields prevent import. You may remove a spurious row or add a missed one manually. Detected symbol, spot and NLV are optional and are applied only if you check the account-field checkbox; a missing NLV is never invented.
7. Import reviewed rows, check the account values, then calculate.

OCR is assistive extraction, not guaranteed accurate recognition. Images are kept only in memory, not included in JSON backups or browser-local portfolio storage. An image missing a field cannot supply it; IV is inferred from the imported midpoint. Entry premiums can be extracted from recognized Trade Price columns and remain reference-only. Cropped or unfamiliar columns may be left blank. First use may be slow on a phone while the model downloads.

Text fallback example (one leg per line): `-2 Jun 19 2027 125 C 0.85 0.95`. Use **Parse text into review table**, correct and confirm, then import.

GitHub documentation: https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site

## Use the calculator

- Select one underlying. Enter its current spot, the account's **current total NLV**, snapshot date, EPR and assumed rate/dividend yield.
- Add one row per option leg. Standard equity options use a multiplier of 100. Negative quantity means short; positive means long. “Shares” uses quantity in shares.
- Enter the **current midpoint per share**, not the entry credit. Optional entry premium is retained as a reference only and does not enter the PNR equation. The bid/ask helper computes a midpoint.
- Leave IV blank to infer a separate IV from each option midpoint. Optionally enter IV in percent to override it. With an override, equity changes are anchored to the modeled snapshot; quote/model discrepancies are flagged.
- Copy original to proposed. Set quantity to zero to close. To roll, enter the new expiry, strike and current midpoint. Keep the remaining legs unchanged. Reduce both put and call quantities to close part of a strangle.
- Enter only **external cash** in cash added/withdrawn. Do not add option sale credits again. At fair value, trade cash flows are offset by the change in option assets/liabilities, leaving NLV unchanged. Fees and adverse slippage reduce proposed NLV.
- Choose the evaluation date and assumed spot on that date. The **+7 days** shortcut keeps spot unchanged. Both original and proposed use the same evaluation conditions.
- IV multiplier 1 keeps the fitted per-leg IVs fixed. 1.25 means an increase from 40% to 50% IV. This shock applies at the evaluation point and all subsequent stress prices; it is illustrative and not a reconstruction of tastytrade's house shocks.
- Calculate. Positive EPR losses consume equity; negative values represent gains. Per-contract loss uses the absolute contract count. PNR changes are shown in percentage points.
- Export JSON for a full backup and CSV for the per-leg breakdown. Clearing the browser's storage removes the local saved project.

## Model and accounting

For each portfolio:

`equity(S, date) = snapshot account NLV + external cash - costs + modeled signed portfolio value(S, date) - modeled signed portfolio value(snapshot spot, snapshot date)`

Original external cash and costs are zero. Proposed uses the supplied adjustments. A short option contributes negative value and a long contributes positive value. This equation incorporates modeled theta, price changes and IV shocks once. Unrelated holdings are held unchanged.

PNR is the nearest detected price move in either direction that reduces this equity to zero, measured from the **evaluation spot**, not necessarily the original spot. The stress loss is evaluated from the **evaluation NLV** at the EPR up/down prices. It is not the actual broker margin requirement.

European Black–Scholes, continuous dividend yield, calendar days / 365, per-leg IV and standard 100-share option multipliers are used. Interest/dividend defaults are editable assumptions, not live rates. Changing the snapshot date requires refreshing quotes. Early exercise, discrete dividends, broker volatility arrays, future skew changes, inter-underlying correlation, concentration surcharges and liquidation decisions are not modeled.

Expired options are valued at intrinsic settlement, with a warning. That is a simplified cash-settlement approximation: physically settled equity options can produce shares and assignment exposure. Update the position table to the actual resulting positions before relying on dates beyond expiration. Cash interest is not added to account NLV.

The numerical search samples 2,400 points per direction, approaching a 100% decline and up to a 1,000% rally, then bisects the first detected sign change. “No crossing found” means none detected within this range; complex nonmonotonic hedge portfolios can have crossings between sample points. American-style quotes can also fail European IV fitting when below its lower bound; this is reported rather than silently altering the input.

“Approx. rally to EPR boundary” uses `(1 + upside PNR)/(1 + EPR) - 1`. This is conditional on a fixed modeled zero-equity price and fixed EPR, not a predicted margin-call cushion. When volatility and time change, the boundary can move.

tastytrade definition: https://tastytrade.com/learn/accounts/account-resources/what-is-portfolio-margin-how-it-works/

## Development and verification

- `core.js`: pricing, IV inversion, equity accounting and numerical roots.
- `app.js`: input tables, comparison, chart, import/export and local persistence.
- `ocr.js`, `screenshot.js`: screenshot geometry/text parsing and browser-local OCR/review flow.
- `styles.css`, `index.template.html`: UI source.
- `index.html`: generated standalone application, ready for direct deployment.
- `build.py`: regenerate standalone HTML after source edits with `python3 build.py`.
- `tests.cjs`: run with `node tests.cjs`; no dependencies.
- `ocr-tests.cjs`: run with `node ocr-tests.cjs`; no dependencies.

Tests cover fitting quote IVs, known PNR examples, close/roll/cash accounting, future theta, entry-premium independence, fees, shares, offsetting hedges, expired options, volatility shocks and put-call parity.

## License

MIT. This is an independent theoretical calculator, not affiliated with tastytrade.

## Validation and privacy

The EPR status badge checks both modeled directions. Signed downside PNR is negative; broker 101% readings are not assumed to be exact zero-equity thresholds. Broker reference inputs are saved/exported with the project but are never used to tune pricing.

Pricing/accounting tests, parser regressions and mocked UI flows cover the model and import safeguards using synthetic data. The complete browser WebAssembly OCR/download flow and visual layout have not been browser-tested. OCR can miss quantity signs and fields; review is mandatory. Images are processed in browser memory and are not persisted in project JSON or local position storage.

Imported price-source labels persist in table rows, saved inputs and JSON exports. Last-price proxies remain visibly marked. Editing a current mark changes its label to Manual mark.
