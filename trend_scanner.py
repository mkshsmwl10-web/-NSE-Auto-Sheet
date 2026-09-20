import yfinance as yf


def get_dynamic_trend(df):
    """
    Dynamic Open -> Close Trend Logic

    POSITIVE trend:
      Current reference OPEN के नीचे candle CLOSE करे
      -> NEGATIVE

    NEGATIVE trend:
      Current reference OPEN के ऊपर candle CLOSE करे
      -> POSITIVE

    अगर trend change नहीं हुआ:
      Current candle का OPEN अगला नया reference OPEN होगा.
    """

    df = df.dropna(subset=["Open", "Close"]).copy()

    if len(df) < 2:
        return "NO DATA", None

    # First candle decides starting trend
    first = df.iloc[0]

    if first["Close"] >= first["Open"]:
        trend = "POSITIVE"
    else:
        trend = "NEGATIVE"

    reference_open = float(first["Open"])

    # Process candles one by one
    for i in range(1, len(df)):
        candle = df.iloc[i]

        candle_open = float(candle["Open"])
        candle_close = float(candle["Close"])

        if trend == "POSITIVE":

            # Close below previous reference open
            if candle_close < reference_open:
                trend = "NEGATIVE"

            # This candle's open becomes new reference
            reference_open = candle_open

        else:  # NEGATIVE

            # Close above previous reference open
            if candle_close > reference_open:
                trend = "POSITIVE"

            # This candle's open becomes new reference
            reference_open = candle_open

    return trend, reference_open


# ---------------- TEST ----------------

symbol = "RELIANCE.NS"

df = yf.download(
    symbol,
    period="6mo",
    interval="1d",
    auto_adjust=False,
    progress=False
)

# yfinance कभी MultiIndex देता है
if hasattr(df.columns, "levels"):
    df.columns = df.columns.get_level_values(0)

trend, ref_open = get_dynamic_trend(df)

print("Stock:", symbol)
print("Daily Trend:", trend)
print("Current Reference Open:", ref_open)
