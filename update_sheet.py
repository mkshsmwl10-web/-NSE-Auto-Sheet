def write_final_sheet(ws, results):

    # Complete old sheet clear
    ws.clear()

    # Exact A:Y header
    values = [OUTPUT_COLUMNS]

    # Exact A:Y data mapping
    for result in results:
        values.append([
            result.get(column, "")
            for column in OUTPUT_COLUMNS
        ])

    # Write exact range
    last_row = len(values)

    ws.update(
        range_name=f"A1:Y{last_row}",
        values=values,
        raw=True
    )

    # Header
    ws.format(
        "A1:Y1",
        {
            "textFormat": {
                "bold": True
            },
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
            "wrapStrategy": "WRAP"
        }
    )

    if last_row >= 2:

        # General alignment
        ws.format(
            f"A2:Y{last_row}",
            {
                "verticalAlignment": "MIDDLE"
            }
        )

        ws.format(
            f"A2:F{last_row}",
            {
                "horizontalAlignment": "CENTER"
            }
        )

        ws.format(
            f"G2:V{last_row}",
            {
                "horizontalAlignment": "RIGHT"
            }
        )

        ws.format(
            f"W2:Y{last_row}",
            {
                "horizontalAlignment": "CENTER"
            }
        )

        # Number formatting
        decimal_columns = [
            "B","C","G","H","I","J","K","L","M",
            "N","O","P","Q","R","S","T","U","V"
        ]

        for column in decimal_columns:
            ws.format(
                f"{column}2:{column}{last_row}",
                {
                    "numberFormat": {
                        "type": "NUMBER",
                        "pattern": "0.00"
                    }
                }
            )

        # Strength Score
        ws.format(
            f"F2:F{last_row}",
            {
                "numberFormat": {
                    "type": "NUMBER",
                    "pattern": "0"
                }
            }
        )

        # Days Since Signal
        ws.format(
            f"X2:X{last_row}",
            {
                "numberFormat": {
                    "type": "NUMBER",
                    "pattern": "0"
                }
            }
        )

    # Freeze
    ws.freeze(rows=1)

    # Filter
    try:
        ws.clear_basic_filter()
    except Exception:
        pass

    if last_row >= 2:
        try:
            ws.set_basic_filter(
                f"A1:Y{last_row}"
            )
        except Exception as e:
            print(f"Filter warning: {e}")

    print(
        f"Final List updated: {len(results)} stocks"
    )
    print(
        "Final List range: A:Y (25 columns)"
    )
