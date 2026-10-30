# Sentinel Security Journal 🛡️

## 2026-10-30 - Adaptive Key Masking for Short Secrets
**Vulnerability:** Static prefix/suffix length (4 leading + 4 trailing characters) in `mask_key()` exposed 88.9% of short/medium API keys (e.g., 8 out of 9 characters revealed for a 9-char key).
**Learning:** Fixed-length key masking heuristics fail on short-to-medium length secrets, leading to near-total secret disclosure in logs or status responses.
**Prevention:** Scale visible prefix and suffix lengths based on total key length so at least 50%+ of the key remains hidden regardless of total length.
