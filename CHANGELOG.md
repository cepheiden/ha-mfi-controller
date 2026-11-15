# Changelog

## 0.1.0

First public release.

- Home Assistant acts as the mFi controller: inform server (TCP 6080) plus STUN and UDP wake-up (UDP 3478).
- Fast switching: UDP wake-up, then the command is returned in the device's next report.
- Per outlet: switch, power, energy (monthly counter), current, voltage, power factor, energy last month.
- Per device: total power and IP address (diagnostic).
- Setup over SSH (reads key and outlet names, sets the inform URL, keeps a backup) or manually.
- Diagnostics with secrets redacted; English and German translations.
