# Security

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Report it privately through GitHub: open the
[Security tab](https://github.com/sakshamm21/tier-hop/security) of this repository and
choose **Report a vulnerability**. Include what you found, how to reproduce it and which
version or commit you tested.

You can expect a first reply within a week. Once a fix is released, the report is
published as a security advisory and you are credited unless you ask not to be.

## Supported versions

Fixes are made on the latest release only.

## What tierhop does with your keys

- Provider API keys are read from the environment or from a `.env` file in the working
  directory. They are held in memory and sent only to the provider they belong to, as a
  bearer token over HTTPS.
- tierhop has no telemetry and makes no network calls other than to the providers you
  have configured.
- The proxy listens on `127.0.0.1` by default. If you bind it to another address, set a
  proxy key with `--api-key` or `TIERHOP_API_KEY`; without one, anyone who can reach
  the port can spend your quota.
- Keep `.env` out of version control. The `.gitignore` in this repository already
  excludes it.
