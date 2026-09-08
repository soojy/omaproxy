# Changelog

## 0.1.2

- Align the popup header with built-in Omarchy panels using PanelHero and the robot icon.
- Replace the running/stopped button with Omarchy’s native toggle, with keyboard and accessibility support.
- Keep the power switch usable when the service is active but its API is unavailable; guard clicks during service transitions.
- Refresh Limits and Accounts screenshots with concealed email labels.

## 0.1.1

- Copy endpoint and API key immediately, without blocking proxy controls.
- Keep cached limits visible when the backend is stopped or unavailable, including after a shell reload.
- Serialize sign-in session updates and ignore stale UI poll results after sign-in actions.
- Keep private sign-in URLs out of timeout errors and detach browser-launch output streams.
- Skip malformed quota records and preserve other accounts' results when one account fails.
- Reject redirects in authenticated local API requests.
- Serialize API-provider additions from OmaProxy instances.
- Expand coverage to 39 Python tests, including isolated backend routing and provider-management checks, plus JavaScript display tests.

## 0.1.0

Initial native Omarchy plugin with Limits, Accounts, and Settings; provider icons; plan labels; click-to-reveal email privacy; and a local CLIProxyAPI user service.
