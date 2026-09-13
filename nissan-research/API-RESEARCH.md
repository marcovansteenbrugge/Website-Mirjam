# Talking to a Nissan EV (Leaf / Ariya) programmatically — Europe / Netherlands

**Research date: 13 September 2026.**
Audience: a private owner in the Netherlands who wants to build a small personal app that
reads battery state and sets cabin temperature.

> **Headline finding.** The API landscape changed twice in the last six months, and almost
> every blog post, forum thread and GitHub README older than ~2 weeks is now wrong.
>
> 1. **30 March 2026** — Nissan shut down the *NissanConnect EV* platform (legacy Carwings).
>    Every Leaf built up to May 2019 and every e-NV200 up to 2022 lost remote services
>    permanently. `pycarwings2` and everything built on it is dead for good.
> 2. **Late August 2026** — Nissan Europe replaced the authentication layer of the surviving
>    platform. The old ForgeRock/OpenAM `kauth` endpoint (`prod.eu2.auth.kamereon.org`) was
>    retired in favour of **MyNISSAN "OneID"**, a WSO2 Identity Server at
>    `login.mynissan-account.com`. The Kamereon data plane survived unchanged.
>
> Net effect: **exactly one auth flow works today**, and only two open-source projects
> implement it (both updated within the last two weeks). Details and sources below.

---

## Table of contents

1. [API generations and which car uses which](#1-api-generations-and-which-car-uses-which)
2. [Authentication — the current European flow](#2-authentication--the-current-european-flow)
3. [Battery read-out](#3-battery-read-out)
4. [Climate control / pre-conditioning](#4-climate-control--pre-conditioning)
5. [Open-source clients compared](#5-open-source-clients-compared)
6. [Practical gotchas](#6-practical-gotchas)
7. [Recommendation](#7-recommendation)
8. [Evidence log: verified vs uncertain](#8-evidence-log-verified-vs-uncertain)

---

## 1. API generations and which car uses which

There have been **three** distinct European Nissan telematics backends. Note that the
premise "Gigya auth for Nissan" that circulates widely is **wrong for Nissan** — Gigya is
the *Renault* identity provider. Nissan EU used ForgeRock, and now uses WSO2.

### Generation 1 — Carwings / "NissanConnect EV" — **DEAD**

| | |
|---|---|
| Vehicles (EU) | Leaf ZE0/AZE0 (2011–2017), Leaf ZE1 built **up to May 2019**, e-NV200 up to 2022 |
| App | *NissanConnect EV* (Android package `com.digitas.android.nissan.carwings`) |
| Base URL | `https://gdcportalgw.its-mo.com/api_v210707_NE/gdc/` |
| Style | PHP endpoints (`InitialApp_v2.php`, `UserLoginRequest.php`, `BatteryStatusCheckRequest.php`, …), password Blowfish-encrypted with a key handed out by `InitialApp_v2.php` |
| Client | `pycarwings2` |
| Status | **Shut down 30 March 2026.** Was already largely broken from 17 May 2024 (`/api_v210707_NE/gdc/InitialApp_v2.php` returning 404). |

Verified: `BASE_URL = "https://gdcportalgw.its-mo.com/api_v210707_NE/gdc/"` in
[`filcole/pycarwings2/pycarwings2/pycarwings2.py`](https://github.com/filcole/pycarwings2)
line 75. Shutdown confirmed by Nissan's own customer notice ("Changes to the NissanConnect
EV App", nissan.co.uk) and tracked in
[home-assistant.io#43711](https://github.com/home-assistant/home-assistant.io/issues/43711)
(opened 24 Feb 2026). Nissan's stated reason: *"the legacy architecture of the current
platform cannot be upgraded to support future enhancements."* Replacement offered to owners:
none — only the in-car Climate Control Timer and Charging Timer.

**For a Netherlands owner this matters twice over**, because these cars were also killed by
cellular sunsets long before the server shutdown (see §6).

### Generation 2 — Kamereon + ForgeRock `kauth` — **DEAD as of ~late Aug 2026**

| | |
|---|---|
| Vehicles (EU) | Leaf ZE1 built **from May 2019**, Ariya (from July 2022), Qashqai, X-Trail, Juke, Townstar, Micra EV |
| App | *NissanConnect Services* (`eu.nissan.nissanconnect.services`) |
| Auth | ForgeRock / OpenAM: `https://prod.eu2.auth.kamereon.org/kauth/`, realm `a-ncb-prod`, callbacks-style `json/realms/root/realms/a-ncb-prod/authenticate`, then OAuth2 code flow with `client_id=a-ncb-nc-android-prod` + a hardcoded client secret, `redirect_uri=org.kamereon.service.nci:/oauth2redirect` |
| Data plane | Kamereon: `alliance-platform-caradapter-prod.apps.eu2.kamereon.io/car-adapter/` etc. |
| Status | Auth layer retired. The **data plane is unchanged and still in use today.** |

Verified from two source trees:
[`mitchellrj/kamereon-python`](https://github.com/mitchellrj/kamereon-python) (older `eu`
cluster) and
[`dan-r/HomeAssistant-NissanConnect` @ tag `v0.7.5`](https://github.com/dan-r/HomeAssistant-NissanConnect/blob/v0.7.5/custom_components/nissan_connect/kamereon/kamereon_const.py)
(`eu2` cluster).

### Generation 3 — Kamereon + **MyNISSAN OneID (WSO2)** — **CURRENT**

| | |
|---|---|
| Vehicles (EU) | Same set as gen 2. Leaf **from May 2019**, Ariya **from July 2022**, plus the 2026 Leaf, Micra EV, and the ICE/e-Power range |
| App | *MyNISSAN app* — this is the **same Android package** `eu.nissan.nissanconnect.services`, simply renamed from "NissanConnect Services" |
| Auth | WSO2 Identity Server, OAuth2 **authorization-code + PKCE** at `https://login.mynissan-account.com/oauth2/{authorize,token}` |
| Data plane | Unchanged Kamereon (`…apps.eu2.kamereon.io`) |
| Status | Live. Rolled out ~last week of August 2026. |

**Region codes:** there are none any more, and this is a real change. Gen 2 asked for a
country code at login. Gen 3 does not: the login is global and the `locale` parameter only
selects the *language of the HTML login form*. Both current clients removed their country
selector for exactly this reason. For a Dutch owner: just log in with the e-mail address you
use in the MyNISSAN app; there is no `nl_NL` to set anywhere in the auth flow. (Dutch does
still exist as a `Language.NL = 'NL'` value used for *notification text* localisation.)

**Base URLs for Europe (verified, identical in two independent codebases):**

```
auth_base_url          https://login.mynissan-account.com/
user_base_url          https://nci-bff-web-prod.apps.eu2.kamereon.io/bff-web/
user_adapter_base_url  https://alliance-platform-usersadapter-prod.apps.eu2.kamereon.io/user-adapter/
car_adapter_base_url   https://alliance-platform-caradapter-prod.apps.eu2.kamereon.io/car-adapter/
notifications_base_url https://alliance-platform-notifications-prod.apps.eu2.kamereon.io/notifications/
```

### Not Europe: North America

Completely separate stack — `https://icm.infinitiusa.com/NissanLeafProd/rest` with an
`API-Key` header, documented in
[BenWoodford's gist](https://gist.github.com/BenWoodford/141ca350445e994e69a70aabfb6db942).
Since ~2022 Nissan USA fetches app secrets at runtime from Firebase and applies SafetyNet
attestation, so headless third-party access is effectively closed there. **Do not copy US
recipes.** Likewise, the PyPI package `pynissan` (see §5) is US/CA/MX only despite its name.

---

## 2. Authentication — the current European flow

Five HTTP steps. This is reconstructed from source I read directly, in two independently
written implementations (Python and Go) that agree on every constant.

### Constants (Europe, MyNISSAN app)

```python
client_id       = 'ZM3WK7ax1OtQKYQ8Qqzcv5VgiA8a'   # public OAuth client of the MyNISSAN Android app
scope           = 'openid name profile email offline_access'
kamereon_scope  = 'openid profile vehicles'
auth_base_url   = 'https://login.mynissan-account.com/'
redirect_uri    = 'com://wso2.service.nci'
auth_brand      = 'Nissan'
auth_client     = 'mynissanapp'
auth_platform   = 'Android'
auth_locale     = 'en_GB'
```

There is **no client secret** (PKCE replaces it) and **no static API key header** — a
genuine simplification versus gen 2.

### Step 1 — GET the authorize endpoint, land on the login form

```http
GET https://login.mynissan-account.com/oauth2/authorize
      ?response_type=code
      &redirect_uri=com://wso2.service.nci
      &client_id=ZM3WK7ax1OtQKYQ8Qqzcv5VgiA8a
      &state=<random>
      &scope=openid%20name%20profile%20email%20offline_access
      &code_challenge=<S256(verifier)>
      &code_challenge_method=S256
      &locale=en_GB
      &brand=Nissan
      &client=mynissanapp
Accept: text/html,application/xhtml+xml,...
```

Follow the 302s **within `login.mynissan-account.com` only**. You must keep a cookie jar:
WSO2 sets a session cookie plus a load-balancer affinity cookie here, and the POST in step 2
fails without both.

You end on an HTML page. Parse out the `<form>` that contains **both** a hidden
`sessionDataKey` input and a `password` input — that is the login form. Keep *all* its
hidden inputs.

### Step 2 — POST the credentials

```http
POST <form action, absolute, must still be on login.mynissan-account.com>
Content-Type: application/x-www-form-urlencoded
Origin:  https://login.mynissan-account.com
Referer: <url of the page from step 1>

sessionDataKey=<from form>&...other hidden inputs...
&userName=<email>
&username=<regionCode>/<email>     # only prefixed if the form carried a regionCode input
&password=<password>
```

Note the quirk, present in both implementations: WSO2 wants **both** `userName` (bare) and
`username` (region-qualified, `NL/you@example.com` style) when the form ships a `regionCode`
hidden field.

Follow redirects until you hit the custom scheme `com://wso2.service.nci?...` — **intercept,
do not follow it.** Verify `state` matches, then take `code`.

**Failure semantics (important for your error handling):** on bad credentials WSO2 does not
return an OAuth error — it **re-renders the login form**. So "response contains a login form
again" == invalid credentials. If you get neither a callback nor a login form, that is *not*
a credentials problem; evcc's message for this case is worth copying verbatim:

> *"login did not complete - open the MyNISSAN app or website, confirm any pending terms,
> consent or verification prompts, then retry"*

### Step 3 — Exchange the code for the OneID token

```http
POST https://login.mynissan-account.com/oauth2/token
Content-Type: application/x-www-form-urlencoded

redirect_uri=com://wso2.service.nci
&grant_type=authorization_code
&client_id=ZM3WK7ax1OtQKYQ8Qqzcv5VgiA8a
&code=<code>
&code_verifier=<verifier>
&scope=openid name profile email offline_access
```

Response is a standard OIDC token set. **You need `id_token`, not `access_token`** — the
OneID access token is useless against Kamereon.

### Step 4 — Exchange the OneID `id_token` for a Kamereon token

```http
POST https://nci-bff-web-prod.apps.eu2.kamereon.io/bff-web/v1/oauth2/access_token?platform=Android
Authorization: <id_token>            # raw JWT, NO "Bearer " prefix
Content-Type: application/vnd.api+json
```

Returns `{access_token, refresh_token, token_type, expires_in}`. *This* access token is the
bearer for every data call. Note the unusual `Authorization: <token>` with no scheme — both
implementations do it this way.

### Step 5 — Resolve user id, then the VIN list

```http
GET https://alliance-platform-usersadapter-prod.apps.eu2.kamereon.io/user-adapter/v1/users/current
Authorization: Bearer <kamereon access_token>
→ { "userId": "..." }

GET https://nci-bff-web-prod.apps.eu2.kamereon.io/bff-web/v5/users/{userId}/cars
→ { "data": [ { "vin": "...", "modelName": "...", "canGeneration": "...",
                "services": [ {"id": 319, "activationState": "ACTIVATED"}, ... ] } ] }
```

The `services[]` array is your **capability map**, and it is also your **subscription
status** — see §6.

### Token lifetime and refresh

```http
POST https://nci-bff-web-prod.apps.eu2.kamereon.io/bff-web/v1/oauth2/refresh-token?platform=Android
Authorization: <kamereon refresh_token>     # again, raw, no "Bearer "
Content-Type: application/vnd.api+json

{"scope": "openid profile vehicles"}
```

- Lifetime comes from `expires_in`. Both clients **fall back to 3600 s** when the field is
  missing, which strongly suggests ~1 hour, but I could **not verify the actual value** —
  neither codebase hardcodes it and I could not reach the endpoint (see §8).
- Correct strategy, as both clients implement it: on **401 or token-expired, try the
  Kamereon refresh once; if that fails, do a full interactive re-login.** Keep the
  username/password — there is no long-lived offline credential you can store instead.
- `offline_access` is requested in the OneID scope, so the WSO2 refresh token exists too,
  but neither client uses it; they refresh at the Kamereon layer.

### CAPTCHA / MFA / attestation — current state

**Verified absent, as of 13 Sep 2026, for Europe.** The flow above is a plain HTML form
POST. There is no CAPTCHA challenge, no device attestation, no Play Integrity check, and no
mandatory MFA in either implementation, and there are no open issues reporting one. Headless
login works.

**But:** the WSO2 login page *can* interject interactive interstitials — pending terms &
conditions acceptance, consent renewals, e-mail verification. When it does, your flow ends
with "no callback and no login form", and the **only** fix is to log into the MyNISSAN app or
web portal by hand and clear the prompt. Build that into your error path from day one.

**Risk note (uncertain):** WSO2 IS ships CAPTCHA-on-failed-attempts and account lockout as
standard features. Whether Nissan has them enabled is unknown. Treat repeated failed logins
as dangerous — see §6.

---

## 3. Battery read-out

### The two-tier model — this is the single most important concept

Kamereon is a **cache in front of a cellular modem**. There are two completely different
operations:

| | "Fetch" (read cache) | "Poll" / "Refresh" (wake the car) |
|---|---|---|
| HTTP | `GET .../battery-status` | `POST .../actions/refresh-battery-status` |
| Talks to the car? | **No** | **Yes**, over cellular |
| Cost | Free, fast-ish | Wakes the TCU, **drains the 12 V battery** |
| Returns | Whatever the car last told the server, with `lastUpdateTime` | An action id; the data arrives *later*, in the cache |
| Safe frequency | every few minutes | see the strategy below |

A `POST refresh-battery-status` does **not** return battery data. It returns
`{"data": {"type": "...", "id": "<action id>"}}`. You then **poll the GET endpoint** and
watch `lastUpdateTime` change.

### Leaf (ZE1, 2019+) — `v1` on the car-adapter

```http
GET https://alliance-platform-caradapter-prod.apps.eu2.kamereon.io/car-adapter/v1/cars/{VIN}/battery-status
Authorization: Bearer <kamereon access_token>
Content-Type: application/vnd.api+json
```

Response `data.attributes` (field names verified from both clients):

| Field | Meaning |
|---|---|
| `batteryLevel` | **State of charge, %** |
| `batteryCapacity` | kWh (see SOH caveat below) |
| `batteryBarLevel` | same thing on the dashboard-bar scale, `240` = 100 % |
| `batteryTemperature` | units ambiguous — the Python client's own comment says `# Fahrenheit?` |
| `rangeHvacOff` / `rangeHvacOn` | **remaining range, km**, with climate off / on |
| `chargeStatus` | `-1` error, `0` not charging, `1` charging |
| `plugStatus` | `-1` error, `0` unplugged, `1` plugged in |
| `chargePower` | charging speed class: `1` slow, `2` normal, `3` fast, `4` fastest, `5` adaptive |
| `instantaneousPower` | kW |
| `timeRequiredToFullFast` / `…Normal` / `…Slow` | minutes |
| `vehiclePlugTimestamp` / `vehicleUnplugTimestamp` | ISO-8601 |
| **`lastUpdateTime`** | **ISO-8601 — how stale your data is. Everything hinges on this.** |

evcc additionally supports a `v2` variant of the same path whose response carries
`timestamp` and `batteryAutonomy` instead of `lastUpdateTime`/`rangeHvacOff`.

### Ariya (and Micra EV) — `v3` on the **bff-web** host, not the car-adapter

```http
GET https://nci-bff-web-prod.apps.eu2.kamereon.io/bff-web/v3/cars/{VIN}/battery-status?canGen={canGeneration}
```

`canGeneration` comes from the vehicle object in step 5. Field names drift:
`batteryAutonomy` instead of `rangeHvacOff`, `chargingRemainingTime` instead of the three
`timeRequiredToFull*`, and `chargingStatus` *or* `chargeStatus`. Write your parser to accept
both spellings — the current Python client does exactly that, with try/except around each.

### State of health

**Not exposed by any client I read.** The vehicle `services[]` list does contain
`BATTERY_STATE_OF_HEALTH_PERCENT = '323'` and `BATTERY_MONITORING = '345'`, so the platform
clearly models SOH somewhere, but no open-source client reads an SOH field, and I could not
verify a field name or endpoint. **Do not assume you can get SOH.** `batteryCapacity` is
present but is generally the nameplate capacity, not a degradation figure.

If you actually need SOH, the realistic route for a Leaf is an **OBD-II dongle** (LeafSpy
protocol), not the cloud API.

### Latency

- `POST refresh-battery-status` → fresh `lastUpdateTime`: **tens of seconds to ~2 minutes**
  when the car is reachable. evcc hardcodes `refreshTimeout = 2 * time.Minute` and gives up
  after that; the Python client polls `5 × 10 s`.
- The API itself is slow even for cached reads: evcc sets an HTTP client timeout of
  **120 seconds** with the comment *"api is unbelievably slow when retrieving status"*.
  Budget for that; do not set a 10-second timeout and call it broken.
- A car that is asleep, out of coverage, in an underground garage, or in privacy mode will
  simply never update. Handle "refresh timed out" as normal, not exceptional.

### Rate limits

**No documented numeric rate limit found, and I could not verify one empirically.** Nobody
in the issue trackers reports 429s from the EU car-adapter. The real constraint is not the
server — it is your 12 V battery.

### Recommended polling strategy

This is the consensus of `leaf2mqtt`, the HA integration and evcc, and it is well-founded:

```
Cached GET (fetch)              every 10–15 min          always safe
Wake the car (refresh):
  parked, unplugged             every 60 min  — or not at all
  plugged in AND charging       every 15 min
  plugged in, NOT charging      revert to the slow interval after ~4–5 consecutive polls
  HVAC command just sent        every 60 s, for ~10 attempts, then stop
```

Rules worth stealing verbatim:

- **Default the wake-the-car poll to OFF.** The HA integration ships
  `DEFAULT_INTERVAL_POLL = 0` (disabled) and `DEFAULT_INTERVAL_FETCH = 10` (minutes). Only
  cached reads happen unless you opt in.
- **The plugged-but-not-charging trap.** A charger that has finished, or a load-balancing /
  smart charger that has paused, leaves the car plugged in for days. Naively "poll fast while
  plugged in" then hammers a sleeping car around the clock. The HA integration counts
  consecutive plugged-not-charging polls and after 4 falls back to the slow interval. Copy
  this.
- **Read `lastUpdateTime` before you wake anything.** evcc's pattern: if the cached reading
  is younger than `expiry` (default **5 minutes**), just use it. Only if it is staler do you
  fire a single `refresh`, then poll the cache until `lastUpdateTime` moves or 2 minutes
  elapse. Never fire a second refresh while one is in flight (the Python client guards this
  with a non-blocking mutex and raises `RefreshInProgressError`).
- **Take the 12 V warning seriously.** From the `leaf2mqtt` docs: *"Long term polling …
  without regular (weekly) usage/charging could drain your 12V battery … if you're not using
  the Leaf frequently, you should stop the container or drastically reduce the update
  frequency, or you could well end up with a flat 12V battery."* A Leaf with a flat 12 V will
  not charge, will not unlock, and will not answer the API — the failure mode is a tow truck,
  not a missing data point. **If the car will sit for a holiday, turn your poller off.**

---

## 4. Climate control / pre-conditioning

### One endpoint does start, stop, schedule and cancel

```http
POST https://alliance-platform-caradapter-prod.apps.eu2.kamereon.io/car-adapter/v1/cars/{VIN}/actions/hvac-start
Authorization: Bearer <kamereon access_token>
Content-Type: application/vnd.api+json

{
  "data": {
    "type": "HvacStart",
    "attributes": {
      "action": "start",              // "start" | "stop" | "cancel"
      "targetTemperature": 21,        // ONLY sent when action == "start"
      "startDateTime": "2026-09-14T07:30:00"   // optional → schedules instead of immediate
    }
  }
}
```

- `action: "start"` with no `startDateTime` → **start now**.
- `action: "start"` **with** `startDateTime` (ISO-8601, seconds precision) → **schedule**.
- `action: "stop"` → stop a running session. **Do not send `targetTemperature` with stop.**
- `action: "cancel"` → cancel a *scheduled* session (distinct from `stop`).

Errors come back as `{"errors": [...]}` with HTTP 200 — **check the body, not just the
status code.** That is true of every Kamereon action endpoint.

### Temperature: range and units

- **Celsius.** No unit field exists in the request.
- **16–26 °C**, integer, 1 °C steps. The Python client raises
  `ValueError('Temperature must be between 16 & 26 degrees')` client-side; the HA climate
  entity declares `min_temp=16, max_temp=26, target_temperature_step=1`.
- **There is no "set target temperature" call.** Temperature is a parameter of *starting*
  HVAC. If the user changes the target while HVAC is already running, you must re-issue
  `action: "start"` with the new temperature — which is exactly what the HA integration does.
  If HVAC is off, you just store the number locally until the next start.

### Reading current climate state

```http
GET .../car-adapter/v1/cars/{VIN}/hvac-status
POST .../car-adapter/v1/cars/{VIN}/actions/refresh-hvac-status    # wake the car for fresh HVAC state
```

`data.attributes`: `internalTemperature`, `externalTemperature`, `hvacStatus` (string, `"on"`
/ off), `nextHvacStartDate`, `nextTargetTemperature`, `lastUpdateTime`.

### Confirming the command actually landed

The POST returning 200 means *Nissan accepted the request*, **not** that the car did
anything. The only real confirmation is `hvacStatus` flipping. Proven pattern from the HA
integration:

```
send hvac-start
loop up to 10 times:
    POST refresh-battery-status + refresh-location   (wakes the car)
    GET  hvac-status
    if hvacStatus == desired: done
    sleep 10s
```

Expect **30–90 seconds**. Also drop your battery polling interval to 1 minute while HVAC is
on — the HA integration hardcodes this, because SOC moves fast during pre-conditioning.

### Vehicle-side constraints (these are car limitations, not API limitations)

From the Leaf ZE1 owner's manual and the platform's own notification catalogue:

- **Ignition must be OFF.** Remote climate will not start otherwise.
- **Runtime is capped: ~2 hours plugged in, ~15 minutes unplugged.** The car stops by itself.
- **It works unplugged** (unlike the old ZE0) — it just runs off the traction battery and
  times out sooner. So "only works while plugged in" is a *myth* for the ZE1; what is true is
  that unplugged sessions are short and consume range.
- While plugged in *and* charging, the car enters "climate priority mode" and keeps charging.
- HVAC capacity is limited while on a charger, so on a very cold or hot day it may not reach
  the target.
- The car must be in cellular coverage.

The platform will tell you when it refuses, via notification keys you can subscribe to:
`hvac.vehicle.not.connected.power`, `hvac.traction.battery.low`, `hvac.vehicle.in.use`,
`hvac.technical.issue`, `hvac.autostart`, `hvac.autostop`.

### Capability gate

Only offer climate if the vehicle's `services[]` contains **`366` (`CLIMATE_ON_OFF`)**.
Temperature *selection* is separately gated on **`2042` (`TEMPERATURE`)** and/or
**`307` (`INTERIOR_TEMP_SETTINGS`)** — some cars can start HVAC but not choose a target.

### Other actions on the same pattern (for reference)

`actions/charging-start` (`{"action": "start"|"stop"}`), `actions/refresh-battery-status`,
`actions/refresh-location`, `actions/refresh-lock-status`, `actions/refresh-hvac-status`,
`actions/horn-lights`, `actions/wake-up-vehicle`. **Remote lock/unlock additionally requires
an SRP challenge-response** (`actions/srp-initiates`, `actions/srp-sets`) which **no
open-source client has implemented** — the Python client's `SRP` class is a stub returning
literal `'0'*20` placeholders. Consider remote locking unavailable.

---

## 5. Open-source clients compared

I read the actual auth and battery modules of each of these, not just the READMEs.

| Project | Lang | Last activity | EU gen-3 OneID? | Battery | HVAC | Licence | Verdict |
|---|---|---|---|---|---|---|---|
| **[dan-r/HomeAssistant-NissanConnect](https://github.com/dan-r/HomeAssistant-NissanConnect)** | Python | **v0.8.2, ~7 Sep 2026** | ✅ **yes** | ✅ Leaf v1 + Ariya v3 | ✅ full | MIT | **Best foundation today** |
| **[evcc-io/evcc](https://github.com/evcc-io/evcc)** `vehicle/nissan` | Go | **Sep 2026** | ✅ **yes** | ✅ v1/v2 | ❌ (charging only) | MIT | Best *reference* for auth; no HVAC |
| **[TA2k/ioBroker.nissan](https://github.com/TA2k/ioBroker.nissan)** | JS | **v0.1.19, 13 Sep 2026** | ✅ yes | ✅ | ✅ | MIT | Only current JS option |
| [Tobiaswk/dartnissanconnect](https://gitlab.com/tobiaswkjeldsen/dartnissanconnect) | Dart | 17 Apr 2026 | ❌ **still ForgeRock `kauth`** | ✅ | ✅ | MIT | **Broken since late Aug 2026** |
| [mitchellrj/kamereon-python](https://github.com/mitchellrj/kamereon-python) | Python | ~2020, PoC | ❌ ForgeRock, `eu` cluster | ✅ | ✅ | Apache-2.0 | Historical ancestor only |
| [filcole/pycarwings2](https://github.com/filcole/pycarwings2) | Python | **PyPI 2.14, 29 Dec 2022** | n/a — Carwings | ✅ | ✅ | Apache-2.0 | **Dead. Server gone 30 Mar 2026** |
| HA core `nissan_leaf` | Python | still shipped, `pycarwings2==2.14` | n/a — Carwings | — | — | Apache-2.0 | **Non-functional since 17 May 2024** |
| [remuslazar/homeassistant-carwings](https://github.com/remuslazar/homeassistant-carwings) | Python | 2025 | n/a — Carwings | ✅ | ✅ | MIT | Well-built, but its backend no longer exists |
| [hacf-fr/renault-api](https://github.com/hacf-fr/renault-api) | Python | **0.5.13, 27 Aug 2026** | **Renault only** | ✅ | ✅ | MIT | Excellent — **but not Nissan** |
| [jamesremuscat/pyze](https://github.com/jamesremuscat/pyze) | Python | PyPI 0.6.0, **Aug 2020** | Renault only, stale | ✅ | ✅ | MIT | Superseded by renault-api |
| `pynissan` (PyPI) | Python | 0.2.1, 2 Aug 2026 | **US/CA/MX only** | ✅ | ✅ | MIT | **Trap** — looks perfect, wrong continent |
| carwingsjs / cw2sjs / carwings2 / leaf-connect (npm) | JS | various | n/a — Carwings | ✅ | ✅ | mixed | All dead with Carwings |

### Notes on the important ones

**`dan-r/HomeAssistant-NissanConnect` — the recommendation.**
Despite being packaged as a Home Assistant integration, the interesting part is a
**self-contained, dependency-light Python package vendored at
`custom_components/nissan_connect/kamereon/`** (two files: `kamereon.py` ~1280 lines,
`kamereon_const.py` ~500 lines). It imports only `requests`, `requests_oauthlib`/`oauthlib`
and the standard library — **no Home Assistant imports at all**. You can copy that directory
into a plain Python project and use it directly:

```python
from kamereon import NCISession, HVACAction

s = NCISession(region="EU")
s.login("you@example.com", "password")

for v in s.fetch_vehicles():
    v.fetch_all()
    print(v.model_name, v.battery_level, "%", v.range_hvac_off, "km",
          v.charging, v.plugged_in, v.battery_status_last_updated)

    v.set_hvac_status(HVACAction.START, 21)   # start pre-conditioning at 21 °C
    # v.set_hvac_status(HVACAction.STOP)
```

Health signals I verified today: **6 open issues, none about authentication**; the two
"Invalid credentials" reports (#117 opened 28 Aug 2026, #123, #125) are all **closed**, fixed
by PR #121 *"Fix MyNISSAN OneID authentication following application changes"*, merged
**1 Sep 2026**. Issue activity as recent as **11 Sep 2026**. `main` is byte-identical to tag
`v0.8.2`. The maintainer turned the OneID migration around in roughly three days.

Caveats: it is not on PyPI, there is no semver contract, the API is synchronous
(`requests`), and it is a hobby project with one maintainer.

**`evcc` — read it even if you write Python.** `vehicle/nissan/identity.go` is the clearest
write-up of the OneID flow in existence, with genuinely useful comments (cookie-jar
requirement, the `userName`/`username` duplication, "Nissan re-renders the login form instead
of redirecting when the credentials are rejected", "the login is not region specific"). It
**independently derives the same `client_id` `ZM3WK7ax1OtQKYQ8Qqzcv5VgiA8a`** — which is the
strongest evidence available that these constants are correct and current.

**`renault-api` — right plumbing, wrong brand.** It is by far the best-engineered client in
this space (async, typed, 1449 commits, released 27 Aug 2026, proper docs). But it targets
`accounts.eu1.gigya.com` + `api-wired-prod-1-euw1.wrd-aws.com` with Gigya API key
`3_VgdkgtIRH3AdHvJm-cjV2ug2EFE0lxt0IJzMC4MFqZjFpn_GYFXVdNZ19L7wZX0N` and Kamereon key
`YjkKtHmGfaceeuExUDKGxrLZGGvtVS0J`. **Nissan EU uses a different identity provider and a
different Kamereon cluster.** It is worth reading for structure and for its `MIN_SOC`/
`MAX_SOC` guard-rail ideas, but it will not talk to your car.

**`dartnissanconnect` — the cautionary tale.** Committed as recently as 17 April 2026 and
still shows repo activity, so it *looks* alive. But its `nissanconnect_session.dart` still
hardcodes `a-ncb-nc-android-prod` against `prod.eu2.auth.kamereon.org/kauth/`. It has not
been updated for OneID and therefore **cannot log in today**. Anything downstream of it
(`leaf2mqtt`, `carwingsflutter`) is in the same position unless separately patched. This is
the trap to avoid: "recent commits" ≠ "works".

---

## 6. Practical gotchas

**1. Your car may simply not be supported any more.**
The dividing line is a **build date, not a model year**: Leaf built **before ~May 2019** was
NissanConnect EV and is **permanently dead since 30 March 2026**. Leaf built **from May 2019**
and Ariya from July 2022 are on the live platform. Check the build plate before writing any
code. A "2019 Leaf" could be on either side of the line.

**2. The app must be set up and the car paired first.**
The API has no enrolment flow. The VIN must already appear under your MyNISSAN account, and
the car must have been through the in-car NissanConnect activation. If `v5/users/{id}/cars`
returns an empty `data` array, no amount of API work will fix it — go through the app.

**3. Subscription expiry is the classic silent killer.**
NissanConnect Services is a time-limited subscription (commonly ~3 years from first
registration in Europe; exact NL terms I could **not verify** — nissan.nl was unreachable).
When it lapses you usually **still authenticate fine** and **still see the vehicle** — the
entries in `services[]` just stop saying `ACTIVATED`. Symptoms: empty or error-bearing
responses from `battery-status`, HVAC silently no-op.
**Therefore: gate every feature on `services[]`, and surface "subscription inactive" as a
distinct state from "network error".** Relevant ids: `319` BATTERY_STATUS, `366`
CLIMATE_ON_OFF, `2042` TEMPERATURE, `307` INTERIOR_TEMP_SETTINGS, `299`/`303` charging
start/stop, `235` DRIVING_JOURNEY_HISTORY, `12` MY_CAR_FINDER, `284` SERVICE_SUBSCRIPTION.

**4. 2G/3G sunset — this is why old Leafs are doubly dead in NL.**
Dutch network history: **Vodafone shut 3G on 4 February 2020**; **KPN shut 3G on 31 March /
1 April 2022**; **Odido (ex-T-Mobile) shut 2G in June 2023**; **KPN's 2G now runs until
1 December 2027** (pushed back from Dec 2025); Vodafone commits to 2G at least through end
2026 *(per ACM; treat exact dates as approximate)*. Leaf ZE0/AZE0 shipped a 2G and later 3G
TCU. Many of those cars lost connectivity years before Nissan turned the servers off. The ZE1
is 4G/LTE and unaffected.

**5. Account lockout — be careful.**
No lockout policy is documented and none is visible in either client. But WSO2 IS ships
account lockout and CAPTCHA-after-N-failures as stock features, and this is your real Nissan
account. **Never retry a failed login in a loop.** Distinguish `NissanAuthError` (bad
credentials → stop, ask the user) from transient errors (→ exponential backoff). The HA
integration makes exactly this distinction and PR #121 explicitly improved it.

**6. Password changes and outages are entangled.**
Issue #117 is instructive: a Nissan outage, then a password reset, then persistent
"Authentication Failed" — which turned out to be the platform migration, not the password.
When login breaks, check whether the *official app* still works before assuming your code is
at fault.

**7. `{"errors": [...]}` inside HTTP 200.**
Kamereon returns JSON:API-style error arrays with a 200 status on the action endpoints. If
you only check `response.ok` you will treat failures as successes.

**8. The API is slow.** 120-second client timeouts, per evcc. Not a bug.

**9. Ariya is a different shape.** Different host (`bff-web` not `car-adapter`), different
path version (`v3`), a required `canGen` query parameter, and renamed fields. Branch on
`modelName` / `canGeneration` rather than assuming.

**10. Privacy mode.** The vehicle object carries `privacyMode`. If the driver enabled it in
the car, location and some telemetry stop flowing regardless of subscription.

**11. Remote lock/unlock needs SRP and nobody has implemented it.** Treat as unavailable.

**12. Plugsurfing live charge-point data in the car was discontinued in March 2026** for
Ariya and Leaf in NL. Unrelated to your app, but it is the other thing owners noticed
changing this year — don't confuse the two announcements.

**13. Legitimate alternative routes**, if you would rather not depend on a reverse-engineered
private API:
- **EU Data Act** — since **12 September 2025** EU owners can formally request their vehicle
  data from Nissan (Nissan has published request pages per market). Almost certainly a
  request/export process rather than a real-time API; I could **not verify** the mechanics,
  as Nissan's pages were unreachable from here.
- **Smartcar** — a commercial normalised-API broker that lists Nissan support. Adds a
  third party, a subscription, and its own regional caveats. Unverified for NL.
- **OBD-II dongle** (LeafSpy-style) — the only reliable route to true SOH, and immune to
  every cloud change described in this document. But it cannot pre-condition the cabin.

---

## 7. Recommendation

### Before writing any code — 10-minute feasibility check

1. **Find the build date on the door plate.** Before ~May 2019 → stop. That car's platform
   was switched off on 30 March 2026 and nothing can bring it back; your only options are an
   OBD-II dongle or the in-car timers.
2. **Install the MyNISSAN app**, log in, confirm the car appears and that remote climate
   actually works from the app. If it does not work there, it will not work from your code.
3. **Clear any pending terms/consent prompts** while you are in there — they will otherwise
   silently break headless login.

### The stack

**Python 3.11+, building on the vendored `kamereon` package from
`dan-r/HomeAssistant-NissanConnect` v0.8.2.**

Why this and not the alternatives:

- It is **the only Python implementation of the current OneID auth flow** that exists. Every
  other Python option is either dead (`pycarwings2`, `kamereon-python`), a different brand
  (`renault-api`, `pyze`) or a different continent (`pynissan`).
- It is **dependency-light and HA-free** — `requests` + `requests_oauthlib` + stdlib. It
  drops into a plain script or a FastAPI app unchanged.
- It covers **both** things you asked for: battery read-out *and* HVAC with target
  temperature, for both Leaf and Ariya.
- It is **demonstrably maintained**: the platform changed in late August 2026 and the fix
  shipped on 1 September 2026.
- MIT licensed.

Concretely:

```
your-app/
  vendor/kamereon/          # copied from custom_components/nissan_connect/kamereon/
    __init__.py  kamereon.py  kamereon_const.py
  app.py
  state.json                # cached last-known reading
```

Pin the exact upstream commit you copied in a comment, and watch the repo — you *will* need
to re-copy after the next Nissan change.

### Architecture

- **A small long-running poller + a tiny HTTP/UI layer.** Not a serverless function: login is
  expensive (5 round-trips through an HTML form) and you want to keep a warm session.
- **Never call Nissan from your UI request path.** The poller writes the last known state to
  a file or SQLite; the UI reads that. Otherwise a 120-second Nissan stall becomes a
  120-second page load.
- **Always show `lastUpdateTime` in the UI**, as "updated 14 minutes ago". This is a
  cache-backed API; pretending otherwise will confuse you and anyone else using it.
- **Two buttons, not one.** "Refresh (cached)" and "Wake car & refresh" should be visibly
  different actions, because one is free and the other costs 12 V charge.

### Polling defaults to ship with

```
cached GET battery-status         every 15 min      (always)
wake-the-car refresh              OFF by default
  while charging                  every 15 min
  parked & unplugged              every 60 min, or off
  after an HVAC command           every 60 s for ~10 min, then back to normal
holiday / long-idle               a manual kill switch — use it
```

Reuse evcc's logic exactly: only fire a refresh if `lastUpdateTime` is older than ~5 minutes,
allow one refresh in flight at a time, and give up after 2 minutes.

### Auth handling

- Store the e-mail and password in the OS keyring or an env var — **there is no long-lived
  token you can store instead**; OneID `offline_access` is not usable for a cold start in any
  current client.
- Keep the Kamereon access + refresh tokens in memory; refresh on 401; full re-login only if
  refresh fails.
- **Do not retry authentication failures automatically.** Surface them, stop, and tell the
  user to check the MyNISSAN app.

### Climate, concretely

```python
v.set_hvac_status(HVACAction.START, 21)        # start now at 21 °C
v.set_hvac_status(HVACAction.START, 21, start=datetime(2026, 9, 14, 7, 30))  # schedule
v.set_hvac_status(HVACAction.STOP)             # stop
v.set_hvac_status(HVACAction.CANCEL)           # cancel a schedule
```

Clamp to 16–26 °C in your UI. After sending, poll `hvac-status` every 10 s for up to ~90 s
and only then report success or a timeout. Remember that "set the temperature" while running
means "re-send start with the new temperature".

### What to keep an eye on

Watch `dan-r/HomeAssistant-NissanConnect` releases and `evcc-io/evcc` `vehicle/nissan/`.
When Nissan next moves the goalposts, one of those two will have a fix within days, and
diffing their constants against yours is a 30-second job. Given that Nissan has now changed
this platform twice in six months, **assume it will break again and design for a quick
constants swap** — keep all URLs and ids in one module, exactly as both reference projects do.

### If you want lower maintenance instead

Run **evcc** or **Home Assistant + the HACS "NissanConnect [EU]" integration** and build your
personal app against *their* local API (evcc's REST/MQTT, or the HA REST API). You inherit
someone else's maintenance burden for the Nissan side, which for an API this volatile is a
genuinely rational trade.

---

## 8. Evidence log: verified vs uncertain

### Verified by reading source or primary documents (13 Sep 2026)

- All gen-3 constants and every endpoint path in §2–§4 — read from
  `custom_components/nissan_connect/kamereon/{kamereon.py,kamereon_const.py}` on `main`
  (byte-identical to tag `v0.8.2`) of `dan-r/HomeAssistant-NissanConnect`.
- **Independent corroboration** of `client_id`, auth base URL, redirect URI, scopes, the
  `id_token`→Kamereon exchange, and the three Kamereon hostnames — from
  `evcc-io/evcc` `vehicle/nissan/{identity.go,api.go,types.go,provider.go}`, a separately
  written Go implementation.
- Gen-2 constants (ForgeRock `kauth`, `a-ncb-nc-android-prod`) — from
  `dan-r/…@v0.7.5`, `mitchellrj/kamereon-python@master`, and
  `tobiaswkjeldsen/dartnissanconnect@master`.
- Carwings base URL — `filcole/pycarwings2@master`, line 75.
- HVAC 16–26 °C, integer, Celsius — client-side validation in `kamereon.py` and the HA
  climate entity attributes.
- Polling logic, the plugged-not-charging counter, `DEFAULT_INTERVAL_POLL = 0` —
  `coordinator.py`, `const.py`, README.
- evcc `expiry = 5 * time.Minute`, `interval = 15 * time.Minute` (`vehicle/config.go`),
  `refreshTimeout = 2 * time.Minute` and the 120 s HTTP timeout (`vehicle/nissan/`).
- Release/commit dates: PR #121 merged 1 Sep 2026; `kamereon_const.py` touched by
  "v0.8.0 release (#121)" on 1 Sep 2026; 6 open issues, newest 11 Sep 2026, none about auth.
- `dartnissanconnect` last commit 17 Apr 2026, MIT (GitLab API), still on ForgeRock.
- PyPI: `renault-api` 0.5.13 (2026-08-27), `pycarwings2` 2.14 (2022-12-29),
  `pyze` 0.6.0 (2020-08-19), `pynissan` 0.2.1 (2026-08-02, US/CA/MX only).
- `renault-api` Gigya/Kamereon constants incl. `nl_NL` locale — `src/renault_api/const.py`.
- HA core still ships `nissan_leaf` with `pycarwings2==2.14`; issue #117674 closed
  "not planned".
- NissanConnect EV shutdown 30 Mar 2026, Leaf ≤ May 2019 + e-NV200 ≤ 2022 —
  home-assistant.io#43711 and Nissan's customer notice (via search extract).
- ioBroker.nissan v0.1.19 (13 Sep 2026) adopting MyNISSAN OneID.

### Explicitly uncertain — do not treat as fact

- **Live reachability of every Nissan endpoint.** The research environment's egress proxy
  blocked `login.mynissan-account.com`, `*.kamereon.io`, `prod.eu2.auth.kamereon.org`,
  `gdcportalgw.its-mo.com`, `nissan.nl`, `nissan.co.uk`, `nissan.ie` and
  `community.home-assistant.io`. **Nothing in this report was confirmed against a live
  server.** Confidence rests on two independent, actively-maintained implementations
  agreeing, plus an issue tracker that is quiet as of two days ago.
- **Token lifetimes.** `expires_in` is server-supplied; the 3600 s figure is only both
  clients' fallback default.
- **Rate limits.** None documented, none found in any issue tracker, none tested.
- **State of health.** No verified field or endpoint. Feature ids `323`/`345` exist; that is
  all I can say.
- **`batteryTemperature` units.** The source comment literally says `# Fahrenheit?`.
- **NL subscription duration and pricing.** Unverified — nissan.nl unreachable.
- **CAPTCHA / lockout policy.** Absent from the current flow; whether WSO2's built-in
  protections are configured is unknown.
- **Exact v0.8.1/v0.8.2 release dates.** GitHub shows relative dates; September 2026 is
  inferred from the PR #121 merge date of 1 Sep 2026.
- **NL 2G/3G dates** are from press and ACM summaries, not operator announcements; the
  Odido-3G-until-Aug-2026 figure in particular looks inconsistent with its earlier shutdown
  and should be re-checked if it matters.
- **EU Data Act mechanics and Smartcar's Nissan coverage** — search extracts only; both
  sites were blocked.

### Deliberately not invented

No endpoint URL, API key, client id or field name in this document was guessed. Everything is
transcribed from source I read. Where I could not find something — SOH, rate limits, exact
token TTL — it is marked as missing rather than filled in.

---

### Key sources

- https://github.com/dan-r/HomeAssistant-NissanConnect (and `v0.7.5`, `v0.8.2` tags, PR #121, issues #117 #123 #125)
- https://github.com/evcc-io/evcc/tree/master/vehicle/nissan
- https://github.com/mitchellrj/kamereon-python
- https://gitlab.com/tobiaswkjeldsen/dartnissanconnect
- https://github.com/filcole/pycarwings2
- https://github.com/hacf-fr/renault-api
- https://github.com/TA2k/ioBroker.nissan
- https://github.com/home-assistant/home-assistant.io/issues/43711
- https://github.com/home-assistant/core/issues/117674
- https://www.nissan.co.uk/owners/nissanconnect-app-changes.html
- https://gist.github.com/BenWoodford/141ca350445e994e69a70aabfb6db942 (North America)
- https://github.com/mitsumaui/leaf2mqtt (polling / 12 V guidance)
- https://www.acm.nl/system/files/documents/gevolgen-afschakeling-2g-3g.pdf
