"""Fetch a live JPY->EUR rate. Uses Frankfurter (ECB data, free, no API key).

Falls back to a placeholder if the network call fails so the pipeline never breaks.
"""

import json
import urllib.request

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest?base=JPY&symbols=EUR"
FALLBACK_RATE = 0.0060  # used only if the live call fails

# Mercari doesn't expose its FX rate via the API (rates are server-side only).
# Its displayed EUR price ≈ interbank rate × this factor (an ~6.3% FX margin),
# calibrated from a real listing: €256.26 / ¥44,800 = 0.005720 vs interbank 0.00538.
# Re-calibrate if Mercari's displayed prices drift from ours.
MERCARI_FX_MARKUP = 1.0632


def get_jpy_to_eur(timeout: float = 10.0) -> tuple[float, str]:
    """Return (rate, source). `source` is 'frankfurter:<date>' or 'fallback:<reason>'."""
    try:
        req = urllib.request.Request(FRANKFURTER_URL, headers={"User-Agent": "japanese-fashion/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        rate = float(data["rates"]["EUR"])
        return rate, f"frankfurter:{data.get('date', '?')}"
    except Exception as e:  # noqa: BLE001
        return FALLBACK_RATE, f"fallback:{type(e).__name__}"


def get_mercari_jpy_to_eur(timeout: float = 10.0) -> tuple[float, str]:
    """Live interbank rate × Mercari's FX markup, to match Mercari's displayed EUR price."""
    rate, src = get_jpy_to_eur(timeout)
    return rate * MERCARI_FX_MARKUP, f"{src}*mercari_markup{MERCARI_FX_MARKUP}"


if __name__ == "__main__":
    r, src = get_jpy_to_eur()
    mr, msrc = get_mercari_jpy_to_eur()
    print(f"interbank: 1 JPY = {r} EUR  ({src})")
    print(f"mercari  : 1 JPY = {mr} EUR  ({msrc})")
