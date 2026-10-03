# SMH screenshot reconciliation

Snapshot date inferred from the supplied expirations/DTE: October 2, 2026. This audit checks model accounting and compares it to broker observations; it does not certify an exact tastytrade implementation.

## Observations

| Figure | Screenshot value |
|---|---:|
| Account NLV | $501,978.34 |
| SMH Last | $630.75 |
| SMH PNR | 26% |
| EPR down / up | 25% / 25% |
| SMH initial and maintenance requirement | $203,026.77 |
| SMH BP Usage | 40.4% |
| SMH Alt Min Extrinsic | $32,765.71 |
| Available option BP | $185,831.41 |

SMH BP Usage agrees with requirement / account NLV: 40.445%. BP Usage is not the margin rate on the underlying holding. Similarly, BOXX’s displayed 15.4% is $77,389.68 divided by account NLV; its position-level margin rate cannot be inferred from that column alone.

The ten displayed requirements total $316,182.53. Account NLV minus available BP is $316,146.93, a $35.60 discrepancy. The screenshots do not establish whether timing, offsets, or another adjustment caused this difference.

## Inputs and price provenance

There are 85 short strangles / 170 short option contracts. Use negative quantities on each leg. The new screenshots’ price columns are Last and Trade Price, alongside P/L columns. They are not bid and ask. Last can be stale; Trade Price is entry basis, not current value. The SMH summary Trade Price 36.93 is not a quote for any individual leg.

| Expiration | Qty each leg | Put / call strikes | Earlier put midpoint | Earlier call midpoint |
|---|---:|---|---:|---:|
| Oct 16, 2026 | -15 | 430 / 715 | 0.085 | 0.390 |
| Nov 20, 2026 | -30 | 390 / 740 | 0.525 | 4.625 |
| Dec 18, 2026 | -20 | 355 / 795 | 0.890 | 4.300 |
| Jan 15, 2027 | -20 | 350 / 910 | 1.255 | 1.835 |

Those earlier midpoints imply $32,722.50 short liability. All these options are out of the money, so modeled liability is entirely extrinsic. It is $43.21 below the broker’s later $32,765.71 extrinsic observation. No exact synchronization is assumed. Rounded entry prices plus displayed P/L cannot reconstruct precise current marks reliably.

## Calculation

For the original portfolio, with other holdings frozen:

`Equity(S,t) = snapshot NLV + signed modeled option value(S,t) - signed modeled option value(S0,t0)`

Proposed equity adds external cash and subtracts fees/adverse slippage. Closing and rolling at fair marks exchange cash for option value; their debits/credits are not added to equity a second time. Existing P/L is already reflected in NLV. Model theta and IV/price repricing are counted once. IV is inferred separately for each leg; the base run holds it fixed as spot moves. Rates are assumptions: 4% interest, 0.5% continuous dividend yield. European Black–Scholes does not model American early exercise or broker-specific skew/volatility stress.

PNR solves equity = 0. EPR is a separate price-stress range and is not a multiplier on NLV or option premiums.

| Check | Model / result |
|---|---:|
| Upside PNR | 26.8817% |
| Upside zero-equity price | $800.31 |
| Downside PNR magnitude | 47.1083% |
| Loss at +25% SMH | $438,654.48 |
| Equity remaining at +25% | $63,323.86 |
| Loss at +15% SMH, fixed IV (illustrative) | $167,054.57 |
| Difference from displayed broker PNR | +0.8817 percentage points |

The broker shows whole percentages. This single observation cannot identify its rounding/truncation convention, price grid, marks, IV treatment, or time convention. The app must not force its output to 26% using an unexplained adjustment. Using the newer Last prices as proxies instead yields about 26.87%; that does not establish those prices as the broker’s marks.

## Margin is a separate calculation

The observed $203,026.77 margin requirement is neither current option liability nor loss at EPR. tastytrade describes concentration when PNR is inside EPR, with expanded price stresses; outside EPR, house stress levels apply. Its risk arrays include price and implied-volatility scenarios. Our fixed-IV +15% loss is illustrative, not a verified SMH house stress setting.

The exact increase if PNR falls below EPR cannot be recovered from these screenshots. Earlier hypothetical statements that margin would jump to a specific NLV-sized amount are not a verified broker rule. A Risk Array at the same timestamp, including price percentages, IV shocks and scenario P/L, plus current bid/ask or marks, is needed to test that behavior. EPR-boundary distance is conditional on the model and is not a margin-call cushion.

BOXX and other symbols are frozen in this one-underlying model. Their displayed 101% PNR readings are not copied into the app as exact zero-equity thresholds; broker display semantics remain unverified.

Source: https://tastytrade.com/learn/accounts/account-resources/what-is-portfolio-margin-how-it-works/ (PNR/EPR definitions and risk-array methodology).

## Changes and verification

- Added editable broker observations alongside model output; these never change the model.
- Corrected the SMH example’s spot/NLV and documented mixed-time quote provenance.
- Prevented P/L / Last / Trade Price screenshots from being treated as bid/ask. Last-as-proxy requires explicit selection; missing marks/signs remain blank.
- Excluded capital-requirements screens and order tickets from position extraction.
- Made the EPR badge check both directions.
- Passed accounting/root regressions, EPR independence, original/reduced/rolled scenarios, price-column regressions, actual SMH image OCR parsing and mocked UI/import tests.
- Full browser OCR/network flow and visual layout are not browser-tested. Local OCR found all eight SMH legs and Last prices; some quantities and an entry price needed manual correction.
