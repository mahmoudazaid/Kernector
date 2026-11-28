# Workspace AI credential vault master key (#461)

Workspace provider API keys are stored encrypted in SQLite. Encryption uses a
**deployment master key** kept outside the database (environment / secrets
manager). Unrelated commands can load Settings without this key; constructing
the vault fails closed if it is missing or invalid.

## Environment variables

| Variable | Required together | Meaning |
| --- | --- | --- |
| `WORKSPACE_CREDENTIAL_MASTER_KEY` | yes | Base64 that decodes to **exactly 32 bytes** |
| `WORKSPACE_CREDENTIAL_MASTER_KEY_VERSION` | yes | Positive integer written as `encryption_key_version` on new rows |

Set both or neither. Partial configuration is rejected at settings load.

## Generate and set (local `.env`)

```bash
# From the repository root
python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
```

Add the output to `.env` (copied from `.env.example`):

```env
WORKSPACE_CREDENTIAL_MASTER_KEY=<paste-base64-here>
WORKSPACE_CREDENTIAL_MASTER_KEY_VERSION=1
```

Example (illustrative only — do not reuse):

```env
WORKSPACE_CREDENTIAL_MASTER_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
WORKSPACE_CREDENTIAL_MASTER_KEY_VERSION=1
```

Confirm length after decode:

```bash
python -c "import base64,os; k=base64.b64decode(os.environ['WORKSPACE_CREDENTIAL_MASTER_KEY'], validate=True); assert len(k)==32"
```

## Operational notes

* Treat the master key like a root secret: do not commit it, log it, or put it
  in issue trackers.
* Keep the same key across restarts for a given deployment. Changing it without
  a migration makes existing vault ciphertext unreadable.
* **Master-key migration / re-encryption is outside #461.** Captured ciphertext
  remains decryptable offline while the unchanged master key is known; durability
  depends on key secrecy, not ciphertext erasure alone.
* Provider env keys (`OPENROUTER_API_KEY`, etc.) are still the transitional
  bootstrap path until workspace SQL cutover (#466).

## Related

* Template comments: [`.env.example`](../.env.example)
* Issue: [#461](https://github.com/mahmoudazaid/Kernector/issues/461)
