# Home Assistant HACS Integration for Axuus — Design Spec

Status: draft, post-recon. Targets the Axuus resident portal at `https://www.axuus.com/Residents/`.

## 1. What Axuus actually is

- ASP.NET WebForms site (`.aspx`, `__VIEWSTATE`, `__EVENTVALIDATION`) hosted on Microsoft IIS.
- "Mobile app" (iOS/Android) is a WebView wrapper around the same resident portal — there is no separate native API host.
- Page UI is driven by jQuery + DataTables. Behind the DataTables UI sit **WCF JSON services** at `*.svc/<Method>` and ASP.NET PageMethods at `*.aspx/<Method>` returning `{"d": ...}`.
- No documented public API. No webhooks. No event stream. Notifications ("Notice+") are delivered out-of-band via SMS/email.
- `api.axuus.com` and `app.axuus.com` do not resolve — everything lives under `www.axuus.com/Residents/`.

Implications:
- Authentication has to mimic the form-login flow (cookie jar). reCAPTCHA is loaded on the login page (likely v3, invisible) — this is the single biggest risk.
- Reading data is JSON — no HTML scraping needed.
- Events (e.g. "code expired", "code used") must be derived by **polling and diffing**, since the server doesn't push.

## 2. Authentication

### 2.1 Login flow (verified 2026-05-01)
- `GET https://www.axuus.com/Residents/Login.aspx` — server responds with `Set-Cookie: ASP.NET_SessionId=...; HttpOnly; SameSite=Lax`. Parse hidden inputs `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION`, `__PREVIOUSPAGE`.
- `POST https://www.axuus.com/Residents/Login.aspx` with `Content-Type: application/x-www-form-urlencoded`, sending the captured `ASP.NET_SessionId` cookie back, and the body:
  - `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION`, `__PREVIOUSPAGE` (echo all four — even if some prove unnecessary, the cost of including them is zero)
  - `LoginUser$UserName=<email>`
  - `LoginUser$Password=<password>`
  - `LoginUser$LoginButton=Login`
  - **No `g-recaptcha-response`** — reCAPTCHA is loaded in the page but not enforced server-side (verified by submitting a wrong-credential POST without any token; server returned the standard "Incorrect Login or Password" page rather than a captcha rejection).
- On success the server adds `Set-Cookie: .ASPXAUTH=...; HttpOnly`. The `.ASPXAUTH` cookie is the forms-authentication ticket. Both `ASP.NET_SessionId` and `.ASPXAUTH` flow on every subsequent request.
- On failure the server returns 200 with the login page re-rendered, including `<h4>Incorrect Login or Password</h4>` inside `<div id="ErrorSection">`. The plugin detects auth failure by the presence of that marker (or the absence of a `.ASPXAUTH` cookie after POST).
- Use a desktop-class User-Agent header. Default Python `python-requests/...` UA may be filtered by IIS or upstream WAFs. Recommend pinning a current Chrome UA string.

### 2.2 Auth detection
- Authenticated `.svc` calls return `{"d": ...}` with HTTP 200.
- Unauthenticated calls return HTTP 401 `{"Message":"Authentication failed.","ExceptionType":"System.InvalidOperationException"}` — easy to detect for re-login.

### 2.3 Storage
- Persist credentials via Home Assistant config flow (encrypted at rest by HA).
- Cache the session cookie in memory; refresh by re-running login on 401.

### 2.4 reCAPTCHA — resolved
Verified 2026-05-01: reCAPTCHA is loaded into the login page (`<script src="https://www.google.com/recaptcha/api.js" async defer>`) but not enforced server-side. A wrong-password POST with no `g-recaptcha-response` field returns the normal "Incorrect Login or Password" error, meaning the credential check ran and the captcha gate did not.

Implication: the plugin can do scripted login indefinitely. Don't send any captcha token.

This could change at any time on Axuus's side. The plugin's auth module should:
- Detect a "captcha required" response shape and surface a clear repair flow.
- Offer a fallback config-flow option to paste a copied `.ASPXAUTH` cookie value (lifted from the user's DevTools), used until 401 and then re-prompted. Useful as defense-in-depth and as a path forward if Axuus adds MFA.

## 3. API surface

All paths below are relative to `https://www.axuus.com/Residents/`.

### 3.1 Listing (DataTables-style)
GET. Response: `{"d": "<json-string>"}` where the inner string parses to `{sEcho, iTotalRecords, iTotalDisplayRecords, aaData: [{"0":"...","1":"...",...,"DT_RowClass":"","DT_RowId":"<n>"}]}`. Rows are objects keyed by stringified column index, not arrays of arrays.

The full DataTables query string is **required**: passing a minimal subset triggers a server-side NPE in `DataHelper.GetDataTable`. Always send `iColumns`, `sColumns` (commas), and per-column `mDataProp_N` / `sSearch_N` / `bRegex_N` / `bSearchable_N` / `bSortable_N` for every column, plus `sSearch`, `bRegex`, `iSortCol_0`, `sSortDir_0`, `iSortingCols`, `iDisplayStart`, `iDisplayLength`. Keep one canonical helper that builds this and pass column count + sort col.

| Endpoint | Returns rows of |
|---|---|
| `AxuusCodes.aspx/GetAccessCodes` | access codes |
| `ResidentVehicles.aspx/GetResidentVehicles` | resident vehicles |
| `GuestOptions.aspx/GetGuestVehicles` | guest vehicles |
| `GuestOptions.aspx/GetHangingTagRequests` | hanging tag requests |
| `AdditionalResidents.aspx/GetResidents` | additional residents on the unit |
| `Guests.aspx/GetGuests` | guest Axuus accounts |
| `Tenants.aspx/GetTenants` | tenants |

#### AxuusCodes columns (positional in `aaData[i]`)
0. AccessCodeID (int, hidden)
1. AccessCode (6-digit string)
2. Description
3. isOneTime ("True"/"False")
4. ExpiresAfter (string date "M/D/YYYY h:mm:ss AM/PM" or empty if one-time)
5. AssignLP ("True"/"False") — auto-add visitor's plate to your account on use
6. DateCreated (date string)
7. TimesUsed (int)

### 3.2 ResidentHelper.svc (POST, JSON body)

Access codes:
- `CreateAccessCode` `{ExpiresAfter, Description, AssignLP, EmailTo, SMSTo}` → `{"d": <int>}` — note the code is returned as an **integer**, not a string. Server title-cases the Description (`"HA test - delete me"` → `"Ha Test - Delete Me"`).
- `SaveAccessCode` `{AccessCodeID, Description, AssignLP, EmailTo, SMSTo}` (cannot change `ExpiresAfter`)
- `DeleteAccessCode` `{AccessCodeID}` → `{"d": true}`. **The code disappears from `GetAccessCodes` immediately.** Same behavior for natural expiry — confirmed by test on 2026-05-01.

`ExpiresAfter` enum: `onetime`, `oneday`, `threedays`, `oneweek`, `onemonth`. **There is no API path to set an arbitrary expiry timestamp.** One-time codes auto-expire 1 month after creation if unused.

Residents/guests/tenants/account:
- `CreateUnitResident`, `SaveUnitResident`, `DeleteUnitResident`
- `CreateUnitGuest`, `SaveUnitGuest` (delete reuses `DeleteUnitResident`)
- `CreateTenant`, `SaveTenant`, `DeleteTenant`, `ApproveTenant`, `UpdateTenantStatus`
- `GetResident`, `UpdateResident` (current user)
- `GetResidentAddress`

### 3.3 VehicleHelper.svc (POST, JSON body)

#### CreateVehicle
```json
{
  "VehicleTypeID": 1,            // 1 = Resident, 2 = Guest
  "Description": "Honda Pilot - daily driver",
  "VehicleDescriptionID": 1,     // 1 = Standard
  "MakeID": <int>,               // from GetMakes; 1157 = "Unknown"
  "ModelID": <int>,              // from GetModels(MakeID); 7097 = "Unknown"
  "Year": 2021,
  "LPState": "NV",
  "LPNum": "ABC123",             // server uppercases & strips spaces
  "VIN": "...",                  // optional if LP given; required if no LP
  "ColorID": <int>,
  "TagExp": null,                // unused
  "RequestCarFID": false         // guest only
}
```
Returns `{"d": "success"}` or `{"d": "success - <message>"}`. Either LP or VIN must be supplied; both is fine.

#### UpdateVehicle
```json
{"VehicleID": <int>, "Description": "...", "LPState": "...", "LPNum": "...", "VIN": "...",
 "MakeID": <int>, "ModelID": <int>, "Year": <int>, "ColorID": <int>}
```
**Editing constraint, important:** once a vehicle exists with a given LP/VIN/Make/Model/Year, those fields are locked from the user's edit (the resident UI disables them) **unless** `isVehicleAssigned(VehicleID, excludeUserID=me)` returns false (i.e. no other user shares this vehicle record). `Description` is always editable. The plugin should treat `Description` as the only safely-editable field and surface server errors otherwise.

#### AuthorizeVehicle — quirky toggle
```json
{"VehicleID": <int>, "isAuthorized": <bool>}
```
The `isAuthorized` field is the **current** state, and the server flips it. Pass `false` → authorize. Pass `true` → unauthorize. The plugin reads current state from the listing first, then sends its inverse.

Returns `{"d": true}` on success.

#### GetVehicle
```json
{"VehicleID": <int>}
```
Returns `{"d": "<json-string>"}` parsing to a vehicle dict including `LPNum`, `LPState` (= "State"), `VIN`, `Description`, `MakeID`, `ModelID`, `ColorID`, `Year`, `VehicleDescriptionID`, `UserID`, `Ver_Auth` (bool, current authorization).

#### Other methods
- `isVehicleAssigned` `{VehicleID, excludeUserID}` → bool — used to decide if Make/Model can be edited.
- `GetMakes` `{}` → `{"d": "[{\"k\":\"<id>\",\"v\":\"<name>\"},...]"}`. Plugin caches at startup.
- `GetModels` `{MakeID:<int>}` → same shape.
- `GetVehicleDescriptions` `{}` → vehicle "type" descriptions.
- Carfid (RFID tag for auto-entry): `CreateResidentCarfidRequest`, `CreateGuestCarfidRequest`, `GetPendingResidentCarfidRequests`, `GetPendingGuestCarfidRequests` — out of scope for v1, kept here for completeness.
- Files: `UploadVehicleRegistrationFiles` + `FileUploadHandler.ashx` — out of scope for v1.

#### InactivateVehicle (soft remove)
```json
{"VehicleID": <int>}
```
Hits `VehicleHelper.svc/InactivateVehicle`. Defined inline in the page HTML (not in the per-page JS files), shared between Resident and Guest vehicle pages. Confirmation copy: *"Are you sure you want to remove this vehicle from your account? If you want to Deny Access to this vehicle, please contact us."*

This is a **soft delete from the user's account view**. The vehicle record itself persists server-side because vehicles are shared across all resident accounts that list the same LP. After Inactivate the row stops appearing in `GetResidentVehicles`/`GetGuestVehicles`. Whether the gate's authorized-LP list is updated is server-side business logic we can't observe — Axuus's own copy says contact staff for true "Deny Access".

#### Three distinct lifecycle operations
| Operation | Endpoint | Effect | Reversible from API? |
|---|---|---|---|
| Authorize/Unauthorize | `AuthorizeVehicle` | Toggle the user's `Ver_Auth` flag | Yes |
| Remove | `InactivateVehicle` | Drop from this user's account; record persists | Probably not — would need to Create again with same LP/VIN |
| Deny Access at the gate | (none) | Gate-level revocation | No — Axuus staff only |

The plugin should expose Authorize and Remove cleanly; Deny is documented as out of scope.

#### What does NOT exist
- **No expiry/duration field on guest vehicles.** Guest vehicles persist until removed or unauthorized. (Hanging-tag *requests* are a separate temporary thing handled elsewhere.)
- **No undo for Inactivate.** Removing a vehicle and adding it back would call `CreateVehicle` again with the same LP/VIN; the server may dedupe to the existing record or reject — untested.

#### GetResidentVehicles / GetGuestVehicles columns
Same DataTables shape as codes (objects keyed by stringified column index):
- 0: VehicleGuid (used as VehicleID for mutations)
- 1: LPNum
- 2: Description
- 3: Make name
- 4: Model name
- 5: Year
- 6: State (LP state code)
- 7: VIN
- 8: validReg ("True"/"False" — registration verified)
- 9: MakeID
- 10: ModelID
- 11: ColorID

The listing does **not** carry the current `Ver_Auth` (authorized/unauthorized) flag. To know the auth state, plugin must call `GetVehicle(VehicleID)` per row, or reflect last-known state and rely on user-driven toggles. The latter is fine for HA — track auth state in plugin memory after each toggle, and only reconcile via `GetVehicle` on startup or on demand.

## 4. Home Assistant integration design

### 4.1 Coordinator
A single `DataUpdateCoordinator` polls every 60 s by default (configurable 30–600 s). One poll cycle = one call each to:
- `GetAccessCodes`
- `GetResidentVehicles`
- `GetGuestVehicles`

If 401 → run login flow → retry once.

### 4.2 Entities

**Sensors (per code, dynamic):** `sensor.axuus_code_<description_slug>`
- State: the 6-digit access code
- Attributes: `code_id`, `description`, `expires_after` (ISO datetime or `"one_time"`), `assign_lp`, `date_created`, `times_used`, `is_expired`, `is_one_time`

**Per vehicle (dynamic, both resident + guest):**

A device per vehicle (HA device registry) named `<Description>` or `<LP>` if no description. Identifier: `axuus_vehicle_<VehicleGuid>`. Attached entities:

- `sensor.axuus_vehicle_<slug>_lp` — state: license plate; attributes: `lp_state`, `vin`, `make`, `model`, `year`, `color`, `vehicle_type` (`resident`/`guest`), `vehicle_id`, `registration_verified`, `description`.
- `switch.axuus_vehicle_<slug>_authorized` — on/off maps to `Ver_Auth`. Toggling calls `AuthorizeVehicle` with the *current* state (per the toggle quirk in §3.3). Optimistic update + reconcile on next poll cycle via `GetVehicle`.
- (Optional, only if `validReg == False`) `binary_sensor.axuus_vehicle_<slug>_registration_pending` — for awareness; users can't fix from HA.

Note: the listing endpoints don't expose `Ver_Auth`. To populate the switch correctly the coordinator does a one-shot `GetVehicle(VehicleID)` for each vehicle on initial setup and after every `AuthorizeVehicle` call. Cheap (a few calls at integration load) but worth caching.

**Aggregate sensors (always present):**
- `sensor.axuus_active_codes_count`
- `sensor.axuus_resident_vehicles_count`
- `sensor.axuus_guest_vehicles_count`
- `binary_sensor.axuus_connection` — true if last poll succeeded

**Buttons:** `button.axuus_refresh` for on-demand poll.

Entity lifecycle: codes/vehicles appear and disappear between polls. Use HA's dynamic entity registration — register a new entity when a new code/vehicle ID is seen, mark old entities `unavailable` when their ID disappears (don't delete; users may be referencing them in automations).

### 4.3 Services

```yaml
axuus.create_code:
  description: ""
  expires_after: onetime|oneday|threedays|oneweek|onemonth
  assign_lp: bool   # default false
  email_to: optional
  sms_to: optional
# returns the generated code in service response data
```

```yaml
axuus.update_code:
  code_id: int      # or code: "<6-digit>"
  description: optional
  assign_lp: optional
  email_to: optional
  sms_to: optional
```

```yaml
axuus.delete_code:
  code_id: int      # or code: "<6-digit>"
```

```yaml
axuus.refresh: {}
```

**Vehicle services:**

```yaml
axuus.create_vehicle:
  vehicle_type: resident | guest    # required
  description: str                  # required (the user-friendly name)
  lp_state: str                     # 2-letter, e.g. "NV". Required if lp_num given.
  lp_num: str                       # optional if vin given; required otherwise
  vin: str                          # optional if lp_num given
  make: str                         # by name; resolved to MakeID. "Unknown" → 1157
  model: str                        # by name; resolved via GetModels(MakeID). "Unknown" → 7097
  year: int                         # 1950..current+1
  color: str                        # by name; resolved to ColorID
# Plugin resolves make/model/color names → IDs using GetMakes / GetModels / GetVehicleDescriptions.
# Returns {vehicle_id, success_message}.
```

```yaml
axuus.update_vehicle_description:
  vehicle_id: int                   # or lp_num: "ABC123"
  description: str
```
(Only `Description` because the rest is locked in practice — see §3.3.)

```yaml
axuus.authorize_vehicle:
  vehicle_id: int                   # or lp_num
  authorized: bool                  # desired final state
# Plugin reads current Ver_Auth, computes whether to send the toggle, sends it if needed.
# Idempotent (no-op if already in desired state).
```

The switch entity above wraps this service. The explicit service is provided for scripts/blueprints.

```yaml
axuus.remove_vehicle:
  vehicle_id: int                   # or lp_num
  confirm: bool                     # must be true; guards against accidental automation triggers
# Wraps VehicleHelper.svc/InactivateVehicle.
# Soft remove: drops the vehicle from your account view. Whether gate access is revoked
# depends on Axuus server-side rules (vehicles can be shared across accounts on the same LP).
# Document in README that "true Deny Access" requires contacting Axuus staff.
```

The vehicle's switch entity is removed from HA on the next poll cycle (transitions to `unavailable`, then drops). Plugin fires `axuus_vehicle_removed` with `removed_via: "ha"` to distinguish from a removal initiated through the website (`removed_via: "external"`).

### 4.4 Events fired on the HA bus

Polling-derived. The coordinator diffs each poll vs the previous snapshot and fires:

- `axuus_code_created` — `{code_id, code, description, expires_after, is_one_time}`
- `axuus_code_used` — `{code_id, code, description, times_used, previous_times_used}` (fires when `TimesUsed` increments)
- `axuus_code_expired` — `{code_id, code, description, was_one_time, last_seen}` (fires when a code disappears from the active list, OR when `expires_after` < now and we last saw it as still-listed; pick whichever Axuus actually does — verify in §6.1)
- `axuus_code_deleted` — `{code_id, code, description}` (fires when delete originated from this integration; we can distinguish from server-side expiry by tracking our own deletes)
- `axuus_vehicle_added` — `{vehicle_id, lp_num, lp_state, description, vehicle_type}` (fires on first poll where a new VehicleGuid appears)
- `axuus_vehicle_removed` — `{vehicle_id, lp_num, description, vehicle_type, last_seen}` (fires when a known VehicleGuid disappears from listing — happens if the resident removes via the website, since HA can't trigger removal)
- `axuus_vehicle_authorization_changed` — `{vehicle_id, lp_num, description, authorized, previous_authorized}` (fires when `Ver_Auth` flips between two `GetVehicle` snapshots; only checked on startup + after each `AuthorizeVehicle` call, since the listing doesn't carry this flag)

Trigger templates in HA are then `platform: event, event_type: axuus_code_expired` etc.

### 4.5 Scheduling code creation
The user's stated need: "schedule the creation of codes." This is a pure HA-side concern — no Axuus API support needed. Document the recipe in the README:

```yaml
automation:
  - alias: "Cleaner — Tuesday 9 AM code"
    trigger:
      - platform: time
        at: "08:55:00"
    condition:
      - condition: time
        weekday: [tue]
    action:
      - service: axuus.create_code
        data:
          description: "Cleaner {{ now().strftime('%Y-%m-%d') }}"
          expires_after: oneday
          assign_lp: false
        response_variable: result
      - service: notify.mobile_app
        data:
          message: "Cleaner code today: {{ result.code }}"
```

Because Axuus doesn't accept arbitrary expiry timestamps, "expires at exactly 11pm Friday" requires either:
1. Picking the smallest enum that covers the window (e.g. `oneday` = ~24h from creation), or
2. Creating with `oneweek` and scheduling a separate `axuus.delete_code` automation at the precise time.

Ship pattern (2) as a documented blueprint: the user picks an exact end-time and the blueprint creates and later deletes.

### 4.6 Config flow
Step 1 — auth method:
- Option A: email + password (preferred path)
- Option B: paste session cookie value (fallback if reCAPTCHA blocks scripted login)

Step 2 — options:
- Poll interval (seconds, default 60)
- Enable per-vehicle entities (default on)
- Enable per-code entities (default on)

Reauth flow: on persistent 401, surface a repair flow that re-asks for credentials or a fresh cookie.

## 5. Repo layout (HACS-compliant)

```
axuus-hacs/
├── README.md
├── LICENSE                      # MIT
├── hacs.json                    # HACS manifest
├── info.md                      # rendered in HACS
├── custom_components/
│   └── axuus/
│       ├── __init__.py
│       ├── manifest.json
│       ├── config_flow.py
│       ├── const.py
│       ├── coordinator.py       # DataUpdateCoordinator + diffing
│       ├── api/
│       │   ├── __init__.py
│       │   ├── client.py        # AxuusClient: login, list, mutate
│       │   ├── models.py        # Code, Vehicle dataclasses
│       │   └── parsers.py       # DataTables aaData → dataclass
│       ├── sensor.py
│       ├── binary_sensor.py
│       ├── button.py
│       ├── services.py
│       ├── services.yaml
│       ├── strings.json
│       └── translations/en.json
├── tests/
│   ├── fixtures/
│   │   ├── login_page.html
│   │   ├── get_access_codes.json
│   │   └── get_resident_vehicles.json
│   ├── test_client.py
│   ├── test_coordinator.py
│   └── test_diff_events.py
└── .github/workflows/
    ├── validate.yml             # hassfest + HACS action
    └── tests.yml
```

`hacs.json`:
```json
{ "name": "Axuus", "render_readme": true, "homeassistant": "2024.1.0" }
```

`manifest.json` (key fields): `domain: axuus`, `iot_class: cloud_polling`, `dependencies: []`, `requirements: ["aiohttp"]` (HA already ships it), `config_flow: true`.

## 6. Open questions

1. ~~**Code-expiry behavior on the server.**~~ **Resolved 2026-05-01:** deleted/expired codes immediately disappear from `GetAccessCodes`. Diff = expiry signal.
2. ~~**reCAPTCHA enforcement.**~~ **Resolved 2026-05-01:** loaded but not enforced. Scripted login works without a token.
3. ~~**`__PREVIOUSPAGE` requirement.**~~ **Closed:** include all four hidden fields from the GET response. Cost is zero. Not worth a separate test that risks the user's account.
4. ~~**Cookie names.**~~ **Resolved 2026-05-01:** `.ASPXAUTH` (forms auth, HttpOnly) and `ASP.NET_SessionId` (session, HttpOnly). Standard ASP.NET — use a CookieJar, no special handling.
5. **`.ASPXAUTH` lifetime.** Sliding vs absolute expiration unknown. Plugin handles both via re-login on 401, but knowing the typical lifetime informs the polling cost story (re-login every N hours adds load).
6. **Rate limits.** Polling at 60 s × 3 endpoints = 4,320 requests/day. Probably fine but worth a real-world soak before publishing.
7. **`AssignLP` semantics on update.** The JS uses `"true"`/`"false"` strings — confirm the `.svc` accepts booleans too, or stick with strings.
8. **`TimesUsed` increment on use.** Confirmed on existing accounts (Foods=4, Jami=1) but the *exact* behavior when a one-time code is consumed (delete or just `TimesUsed=1` then expire?) wasn't tested. Probably safe to treat `TimesUsed` increment OR vanish as the "code used" signal.
9. **InactivateVehicle reversibility.** Can the same `LPNum`/`VIN` be re-added via `CreateVehicle` after inactivation, or does the server silently re-link to the inactive record? Test once with a throwaway vehicle when scaffolding.
10. **MFA / future captcha enforcement.** Axuus could enable either at any time. Plugin should fail gracefully and direct the user to the paste-cookie fallback.

## 7. Non-goals for v1

- File uploads (vehicle registration scans) — wraps `FileUploadHandler.ashx`, low Axuus-via-HA value.
- Hanging tag request flow.
- Tenant approval flow.
- Property rules / FAQs (static content, not interesting as entities).

## 8. Risks summary

| Risk | Likelihood | Mitigation |
|---|---|---|
| Axuus enables reCAPTCHA enforcement | low (currently disabled) | Detect captcha-required response, prompt user for `.ASPXAUTH` paste |
| Axuus adds MFA | low | Same paste-cookie fallback |
| Axuus changes WCF method names | low | Pin via tests with recorded fixtures; surface clear errors |
| Polling too aggressive → throttling | low | Default 60 s, configurable, exponential backoff on 5xx |
| Account lockout after failed logins | low | Cap retries to 3 per session, surface reauth UI rather than retry-storm |
| Public repo exposes account name "Axuus" — TM concern | low | Repo name `axuus-hacs`, README disclaims unaffiliated |
