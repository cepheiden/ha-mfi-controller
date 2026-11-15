---
name: Bug report / device report
about: Something does not work, or you tested another mFi model
labels: bug
---

**Device**
- Model (e.g. mPower P3E, mPower mini, mPower Pro):
- Firmware (`cat /etc/version` on the device):
- Previously adopted by an mFi Controller? yes / no / factory reset

**Home Assistant**
- Version:
- Installation type (OS / Container / Core):
- Integration version:

**What happened**


**Diagnostics**
Attach the download from *Settings → Devices & services → mFi Controller → ⋮ → Download diagnostics* (secrets are redacted).

**Debug log** (optional)
```yaml
logger:
  logs:
    custom_components.mfi_controller: debug
```
