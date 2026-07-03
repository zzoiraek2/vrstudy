# VR Study Data Example

This folder documents the runtime data shape only. Do not put real databases,
API keys, access tokens, Telegram settings, or account data in the public repo.

Production data should live outside the Git checkout, for example:

```text
/var/lib/vrstudy
```

Point the app at that directory with:

```text
VRSTUDY_DATA_DIR=/var/lib/vrstudy
```

