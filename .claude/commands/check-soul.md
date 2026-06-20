---
description: Validate that soul.md exists at the required path and check its SHA-256 integrity against the stored baseline. Reports drift if detected.
---

Validate the CyClaw soul file at `data/personality/soul.md`.

## Steps

1. Check the file exists:
   ```bash
   test -f data/personality/soul.md && echo "EXISTS" || echo "MISSING"
   ```
   If missing: stop and report — the server will fail to start without it.

2. Compute the current SHA-256:
   ```bash
   sha256sum data/personality/soul.md
   ```

3. Check `utils/personality.py` for the stored baseline hash (look for `soul_hash` or equivalent constant).

4. Compare:
   - **Match** → Soul file is intact. Report the hash and file size.
   - **Mismatch** → Report drift detected. Show current hash vs baseline. Do NOT auto-correct — surface to user for decision.
   - **No baseline found** → Report that no stored hash exists and recommend running the server once to establish a baseline.

5. Additionally check:
   ```bash
   # File is non-empty
   wc -c data/personality/soul.md
   # File is valid UTF-8
   python3 -c "open('data/personality/soul.md').read()" && echo "UTF-8 OK"
   ```

## Output

```
Soul file: data/personality/soul.md
Status:    EXISTS / MISSING
Size:      <bytes>
SHA-256:   <hash>
Integrity: PASS / DRIFT DETECTED / NO BASELINE
```

If drift is detected, list the last-modified timestamp and ask the user whether to accept the new hash as the baseline.
