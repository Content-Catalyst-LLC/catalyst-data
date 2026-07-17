# Accessibility, Offline, and Performance Requirements

## Interface requirements

- Complete keyboard operation and visible focus indicators.
- Programmatic labels for form fields and controls.
- Live status announcements for loading, success, cached fallback, and failure.
- Semantic lists and headings for published records.
- Responsive layouts at narrow widths.
- Reduced-motion support and high-contrast compatibility.
- No reliance on color alone for status.

## Offline behavior

The public embed stores the last successful public API response in browser storage. When the network fails, the embed may display that cached public response with its cache timestamp and an explicit offline notice. It never caches or accepts protected write credentials.

## Performance budgets

The repository benchmark warns when statistics or 100-record page operations exceed 1,000 milliseconds in the current environment. Results are evidence for trend monitoring, not universal service-level guarantees.
