# Swing Accumulation scanner

Run **Actions → Swing Accumulation Scanner → Run workflow**. Results go to the existing workbook's **Swing Accumulation** tab. Input symbols come from **NIFTY200**. The existing GCP_CREDENTIALS secret is reused. Weekday schedule: approximately 8:30 pm IST; GitHub may delay scheduled runs. NSE holidays can repeat the last trading session; always check Data Date.

This is a price/volume heuristic, not proof of institutional purchases, a probability estimate, or a backtested strategy. Delivery, bulk/block deals and institutional holdings are NOT ingested and are explicitly unverified. TradingView links open ordinary stock charts, not custom pattern overlays.

Rules use adjusted daily OHLCV and completed candles only (today excluded before 4 pm IST). The prior 20 sessions form the base. Trend: close > SMA50 > SMA200, with SMA50 rising over five sessions. Base width <=15%; average up-day volume / average down-day volume >=1.3; latest ten base-session lows do not undercut the earlier ten-session low. Flat days are excluded from up/down comparisons.

BREAKOUT requires all four conditions plus close above prior resistance, volume >=1.5x the previous 20-session mean and close in the top 30% of its candle. WATCH requires those four conditions and close within 3% below resistance. No historical retest detection is implemented.

Score: trend 25, base tightness 20, up/down volume 20, support proxy 15, high volume 10, strong close 10. It is a checklist score, not a success percentage. All input stocks are listed, including NO SETUP, so screening coverage is visible.

Indicative entry: breakout close or WATCH resistance +0.1%. Stop: latest five-session low minus 0.5%. Risk must be positive and <=7%, otherwise RISK TOO WIDE. Target is entry +2 times the entry-stop distance. These are references, not executable orders; future fill prices, gaps, slippage and costs change risk. No orders are placed.

Data older than four calendar days is STALE DATA with trade references blank. If valid coverage falls below 80%, the job fails and retains the previous sheet. Run timestamp, data date and workflow status must be checked together. Successful-run CSV and diagnostics are uploaded as a GitHub Actions artifact. Existing scanners and sheets are not modified.
