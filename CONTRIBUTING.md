# Contributing

Small fixes, provider quota adapters, and UI improvements are welcome.

1. Open an issue for substantial changes so we can agree on scope.
2. Keep provider secrets in the Python/backend layer. Only pass allowlisted
   display fields to QML, and send sensitive form input over stdin.
3. Preserve the three tabs: Limits, Accounts, Settings. Keep optional model
   windows out of the default limits view.
4. Run the Python suite, the JavaScript display checks, and Omarchy's manifest
   validator. See the README for commands.
5. Test QML changes in the actual Omarchy shell. Close and reopen the popup before
   capturing screenshots so all emails are concealed.

Use fake accounts and a local mock upstream in tests. Never commit credentials,
private logs, personal email addresses, or screenshots of unrelated applications.
