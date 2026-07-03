# Changelog

## v0.1.62 - 2026-07-03

- Disable the Infinite Method `체결입력 후 주문실행` button whenever today's order table already exists and the normal order execution button is available.
- Enable `체결입력 후 주문실행` only when today's order table is not yet available and the execution input date can be saved.

## v0.1.61 - 2026-07-03

- Rename the Infinite Method execution button and order panel from next-day wording to today's order table wording.
- Add an Infinite Method `체결입력 후 주문실행` button that validates the API execution-preview date, fills the execution form, saves it, refreshes today's order table, and then starts order execution.
- Re-resolve the Kiwoom US stock exchange code immediately before Infinite Method order submission so SOXL orders are sent with the correct exchange code.

## v0.1.60 - 2026-07-03

- Fix the empty-result handling for Kiwoom `ust21180` period order/fill history so return code `20` no longer appears as a failed execution-preview lookup.
- Keep empty-result metadata tied to the correct Kiwoom API ID for balance and fill-history calls.

## v0.1.59 - 2026-07-03

- Treat Kiwoom `ust21180` return code `20` (`조회내역이 없습니다`) as an empty order/fill result instead of a failed API call.
- Keep Infinite Method execution-preview fields updating from the selected profile symbol even when there are no recent fills.
- Clear the preview average price when the selected symbol is not present in the balance response instead of showing a stale or synthetic value.

## v0.1.58 - 2026-07-03

- Resolve Kiwoom US stock exchange codes before symbol-specific balance and fill lookups.
- Use `SOXL -> NA` and `TQQQ -> ND` as local fallbacks so SOXL requests are no longer sent as NASDAQ (`ND`) requests.
- Stop hardcoding `ND` in VR and Infinite Method Kiwoom lookup/order rows.

## v0.1.57 - 2026-07-03

- Preserve local Telegram settings when rebuilding the executable by restoring them into the local `dist\data` folder when needed.
- Recover Telegram settings from the legacy/local `data` folder if the running app's settings file is missing.
- Prevent blank Telegram form values from overwriting an existing Bot Token or Chat ID.
- Create a timestamped backup before writing Telegram settings.

## v0.1.56 - 2026-07-03

- Enable VR order execution based on the displayed order table's `start_date` through `end_date`, not the later calculated order period.
- Use the displayed VR order-table period for current fill lookup and VR order fill exclusion.
- Move startup price refresh into the loading phase so no scheduled price/dashboard refresh starts immediately after the main window appears.
- Reduce startup-time duplicate dashboard rendering and keep the final dashboard render inside the loading phase.

## v0.1.55 - 2026-07-03

- Move startup progress completion to after the main window is restored and rendered.
- Add a `화면 표시 준비 중...` step at 98% so 100% no longer appears before the visible UI is ready.
- Force Tk layout/event processing before closing the startup progress window.

## v0.1.54 - 2026-07-03

- Show the startup progress window as an independent topmost window so it appears while the main window is still loading.
- Keep the main window transparent during startup instead of withdrawing it, then restore and bring it to the front after loading.
- Keep the startup progress window visible briefly even on fast launches so it does not look skipped.

## v0.1.53 - 2026-07-03

- Add a startup progress window so initial DB, profile, dashboard, and UI loading no longer looks frozen.
- Show initialization progress from 1% to 100% with the current startup step.
- Keep the main window hidden until startup loading completes, then open it normally.

## v0.1.52 - 2026-07-03

- Add a VR order execution button that submits remaining current-cycle limit orders through Kiwoom REST.
- Before sending VR orders, fetch current-cycle fills and exclude only matching side/price filled quantities from the order table.
- Enable the VR order execution button only for the order table whose order period contains today.
- Make VR fill-history date separator rows explicit, such as `2026-06-09 체결내역`.

## v0.1.51 - 2026-07-03

- Read Kiwoom credential JSON with UTF-8 BOM support so saved credentials are not treated as an empty store.
- Stop silently replacing an unreadable Kiwoom credential file with a blank credential store.
- Preserve the v0.1.50 VR fill-history split between previous-cycle and current-cycle lookup buttons.

## v0.1.50 - 2026-07-03

- Split the VR fill-history lookup into separate `지난차수 조회` and `현재차수 조회` buttons.
- Keep current-cycle lookup focused on the latest started VR order period through today.
- Add previous-cycle lookup for the immediately preceding VR order period.

## v0.1.49 - 2026-07-03

- Add a VR `체결내역` tab with a Kiwoom `ust21180` lookup button for the active order period.
- Show filled order rows grouped by trade date, including side, filled price, quantity, amount, order number, original order quantity, and status.
- Add a price-level fill summary that can later drive VR order-table quantity exclusion by side and filled price.

## v0.1.48 - 2026-07-03

- Protect saved Kiwoom API credentials from being overwritten by blank API form fields.
- Preserve existing App Key, App Secret, account, expiration, and memo values when a save-triggering API action has empty fields.
- Create a timestamped backup of the Kiwoom credential file before each credential save.

## v0.1.47 - 2026-07-03

- Remove the temporary one-year auto-calculation for Kiwoom API key expiration.
- Keep the API key expiration field as the actual expiration date received at key registration.
- Populate the current saved Kiwoom credential records with the registered `2027-07-03` expiration date.

## v0.1.46 - 2026-07-03

- Auto-fill blank Kiwoom API key expiration fields when an App Key and App Secret are present.
- Use a one-year default expiration date from the save/load date, so keys created today show the expected next-year date.
- Keep OAuth access-token expiration separate from the saved API key expiration field.

## v0.1.45 - 2026-07-03

- Add Kiwoom REST order helpers for US buy (`ust20000`) and sell (`ust20001`) orders.
- Add an Infinite Method order execution button for today's order sheet with a confirmation dialog before any live API request.
- Map Infinite Method order rows to Kiwoom order types: buy limit/LOC and sell limit/LOC/MOC, with per-order success/failure status.

## v0.1.44 - 2026-07-03

- Add a VR Kiwoom API validation field for estimated holding quantity at the selected result-period end.
- Rewind current `ust21070` holdings using `ust21180` filled buy/sell quantities after the result-period end.
- Keep the period-end holding quantity clearly labeled as an estimate because Kiwoom REST docs do not expose direct historical per-symbol holdings.

## v0.1.43 - 2026-07-03

- Add VR Kiwoom API validation fields for buy and sell filled amount totals in USD.
- Sum `ust21180` `cntr_amt` by side, with a `cntr_qty * cntr_uv` fallback when the filled amount is not populated.
- Keep the new amount fields read-only in the API validation box.

## v0.1.42 - 2026-07-03

- Change the VR Kiwoom API validation target to the latest completed result period based on the lookup date.
- Exclude any result period that still contains the lookup date, so July 3 looks up the previous period while July 4 looks up the period ending July 3.
- Show the lookup date and selected target period in the VR API validation status line.

## v0.1.41 - 2026-07-03

- Add a VR Kiwoom API validation box for the selected result period.
- Query `ust21180` over the VR result period and preview buy/sell filled quantity totals.
- Query `ust21070` for the current holding quantity while keeping saved VR cycle inputs untouched.

## v0.1.40 - 2026-07-03

- Use Kiwoom `ust21180` period order history to find the latest order date for the Infinite Method API execution preview.
- Sum buy and sell filled quantities on that latest order date instead of using same-day balance fields.
- Keep average price sourced from `ust21070` while leaving the real execution-entry form untouched.

## v0.1.39 - 2026-07-03

- Remove KRW cash-flow preview from the Infinite Method Kiwoom execution-info API box.
- Stop calling the transaction-history API from execution-info preview, leaving the preview focused on balance-derived date, average price, buy quantity, and sell quantity.

## v0.1.38 - 2026-07-03

- Add an Infinite Method API preview box for execution input fields without touching the real execution-entry form.
- Query Kiwoom balance and transaction APIs to preview input date, average price, buy quantity, sell quantity, and KRW cash flow.
- Keep the preview as a verification-only API tab workflow with no auto-apply or auto-save behavior.

## v0.1.37 - 2026-07-03

- Add profile-scoped Kiwoom access-token reuse and automatic refresh before API calls.
- Add an Infinite Method API `잔고조회` panel that calls the Kiwoom `ust21070` 미국주식 원장잔고확인 endpoint.
- Show balance lookup status and formatted JSON results without exposing raw access tokens.

## v0.1.36 - 2026-07-03

- Allow Kiwoom REST API HTTPS calls to trust certificates from the Windows trusted certificate stores in addition to the bundled `certifi` roots.
- Keep SSL certificate verification enabled while handling PCs where security software or brokerage middleware installs a local trusted certificate chain.

## v0.1.35 - 2026-07-03

- Rework the release build flow so PyInstaller writes to `build\pyinstaller-dist` instead of touching `dist` directly.
- Replace runtime data moving with a read-only build snapshot under `build\data-snapshots`, preserving local `dist\data` during builds.
- Keep local `dist\data\secrets` available after builds while still excluding secrets from release zip packages.

## v0.1.34 - 2026-07-03

- Add a build preflight guard for stale `vrstudy.lock` files so release builds stop before moving runtime data if the app is still using `dist\data`.
- Rebuild release packages after restoring the local `dist\data` database from the preserved pre-build archive.

## v0.1.33 - 2026-07-03

- Improve Kiwoom OAuth failure diagnostics by showing HTTP status, return code/message, and a masked response preview when available.

## v0.1.32 - 2026-07-03

- Add Kiwoom OAuth token issuance testing from each profile's API key tab.
- Cache issued Kiwoom access tokens under local `data/secrets` for later account/quote/order API tests.
- Keep token cache entries synced when profiles are renamed or deleted.

## v0.1.31 - 2026-07-03

- Move Kiwoom REST API key setup into per-profile VR and Infinite Method tabs.
- Store Kiwoom API credentials separately under local `data/secrets`, preserving them for local builds while excluding them from release packages.
- Keep Kiwoom API credentials synced when profiles are renamed or deleted.

## v0.1.30 - 2026-07-03

- Align dashboard left and right panels on a shared 50/50 column grid so the center divider stays consistent across summary, detail, graph, and table sections.

## v0.1.29 - 2026-07-03

- Replace the Infinite Method dashboard detail `average price missing` row with an investment progress row showing T progress, percent invested, and phase.

## v0.1.28 - 2026-07-02

- Recover the lost Infinite Method execution inputs from the archived pre-build `dist\data` database.
- Make release builds prefer the archived pre-build `dist\data` as the current data source, preventing local executable data from being overwritten by stale workspace data.
- Keep release zip packages excluding Telegram credentials while packaging the latest local executable data.

## v0.1.27 - 2026-07-02

- Color Infinite Method order rows by side: buy rows use a light red background and sell rows use a light blue background.
- Add a visual separator row between buy and sell groups in the Infinite Method order table.

## v0.1.26 - 2026-07-02

- Rebuild local `dist\data` from the current workspace data after each build, including DB, profiles, and local Telegram settings.
- Keep release packages free of Telegram credentials while keeping the local built executable ready to run with existing data.

## v0.1.25 - 2026-07-02

- Restore local Telegram settings back into `dist\data` after builds so saved credentials survive local patch builds.
- Keep Telegram settings excluded from release zip packages while preserving them on the developer's local executable folder.

## v0.1.24 - 2026-07-02

- Split Telegram manual-send selections and automatic-send selections into separate UI sections.
- Keep selected-summary sending controls under manual sending and order-calculation sending controls under automatic sending.
- Restore Telegram tab labels to readable Korean text.

## v0.1.23 - 2026-07-02

- Add automatic Telegram sending after VR and Infinite Method order calculations.
- Add Telegram options for automatic send trigger, per-strategy order sending, order-table inclusion, and max order rows.
- Include Infinite Method month-to-date and year-to-date realized profit in KRW conversion in automatic order messages.

## v0.1.22 - 2026-07-02

- Add a Telegram tab with Bot Token and Chat ID settings.
- Add Telegram test message and selected-summary sending actions.
- Add selectable Telegram message sections for due items, dashboard summary, VR summary, Infinite Method summary, and order status.
- Use the Telegram Bot API directly through local Python libraries and package the certifi CA bundle for HTTPS verification.
- Keep Telegram settings out of release packages so distributed builds start with blank credentials.

## v0.1.21 - 2026-07-02

- Add separators to the VR weekly result input form to group period, execution, cash/dividend, and condition sections.

## v0.1.20 - 2026-07-02

- Split Infinite Method execution input into buy quantity and sell quantity.
- Change Infinite Method cash entry to signed cash flow: positive for deposits and negative for withdrawals.
- Add schema migration v2 to convert old net quantity and withdrawal values into the new fields.
- Calculate mixed buy/sell days using sell quantity for realized profit and gross buy plus sell value for fees.

## v0.1.19 - 2026-07-01

- Keep left setup panels fixed while horizontal resizing VR and Infinite Method screens.
- Distribute vertical resize space across right-side tables instead of collapsing only the bottom table.
- Rework dashboard sections to resize evenly in both directions, including expanded graph panels.

## v0.1.18 - 2026-07-01

- Block Infinite Method order generation when yesterday's average price is missing.
- Show a clear "order unavailable" message instead of displaying an order sheet in that state.

## v0.1.17 - 2026-07-01

- Block Infinite Method execution entry for today or future dates and keep generated rows capped at today.
- Disable the Infinite Method execution-save button when the selected input date is today or later.
- Clean up accidental Infinite Method 2026-07-02 rows and clear 2026-07-01 execution input values.
- Split VR G and buy-limit condition inputs into value, period, and step fields while preserving existing calculation config strings.

## v0.1.16 - 2026-07-01

- Removed `%LOCALAPPDATA%\VRStudy` fallback and legacy data import.
- Always store runtime data in the local `data\` folder next to the executable or source checkout.

## v0.1.15 - 2026-07-01

- Force Infinite Method T value to 0 whenever the cumulative holding quantity is 0.

## v0.1.14 - 2026-07-01

- Fixed garbled Korean validation messages in Infinite Method settings and execution entry popups.

## v0.1.13 - 2026-07-01

- Changed the Infinite Method symbol field to a TQQQ/SOXL dropdown.
- Added validation so Infinite Method profiles can only use TQQQ or SOXL.

## v0.1.12 - 2026-07-01

- Corrected Infinite Method principal calculations for normal and compound modes.
- Apply withdrawals to both modes, including negative withdrawals as deposits.
- In compound mode, apply half of realized gains but the full amount of realized losses and fees to the principal.
- Use the calculated basis row principal consistently for the next order plan and displayed per-buy amount.

## v0.1.11 - 2026-06-30

- Split profile files into `data/profiles/vr` and `data/profiles/infinite`.
- Export Infinite Method profile settings to JSON files while keeping DB rows synchronized.
- Migrate old flat VR profile JSON files into `data/profiles/vr` on startup.

## v0.1.10 - 2026-06-30

- Added automated release packaging for empty-data and data-included distributions.
- Move stale runtime data out of `dist` before building to avoid distribution confusion.
- Keep historical backups out of data-included release packages by default.
- Exclude transient files such as `vrstudy.lock`, `*.wal`, and `*.wal.bad-*` from data packages.

## v0.1.9 - 2026-06-30

- Changed the default data location to a `data` folder next to the executable.
- Added first-run migration from the old Windows user data folder into local `data`.
- Updated distribution guidance for empty-data and data-included packages.

## v0.1.8 - 2026-06-30

- Open the app maximized on startup while keeping the standard Windows title bar.

## v0.1.7 - 2026-06-30

- Made Infinite Method today's status view columns resize to the actual visible width.
- Prevented the value column from extending past the right edge of the status view.

## v0.1.6 - 2026-06-30

- Removed the Infinite Method today's status view vertical scrollbar.
- Increased the Infinite Method status view row height and value column width.
- Set a wider default left panel for the Infinite Method tab.

## v0.1.5 - 2026-06-30

- Changed the Infinite Method left panel to match the VR tab concept.
- Moved Infinite Method settings and today's status view into the `프로필 설정` tab.
- Moved Infinite Method execution entry into the separate `체결 입력` tab.

## v0.1.4 - 2026-06-30

- Highlighted the dashboard's current asset and profit rows for quicker scanning.
- Added dashboard due-list row colors for pending and empty states.
- Replaced long footer paths with version, data-folder, and backup-folder controls.

## v0.1.3 - 2026-06-30

- Removed VR profile-level default contribution amount from the profile settings UI.
- Removed VR profile-level buy-limit condition and start week from the profile settings UI.
- Kept contribution and buy-limit inputs in the weekly result entry workflow.

## v0.1.2 - 2026-06-30

- Matched dashboard summary and due panel heights after removing the duplicated due-count row.

## v0.1.1 - 2026-06-30

- Moved dashboard due count into the `대기 / 미작성` panel title.
- Removed duplicated `오늘 처리 필요` row from the main dashboard summary.

## v0.1.0 - 2026-06-30

- Added dashboard summary, KRW totals, cash ratio, and collapsible chart area.
- Added VR week-based settings, G start week, buy-limit start week, and buy-limit progression.
- Added profile numbering, due badges, current-row navigation, and calculation pause controls.
- Added startup/close DB stability safeguards, single-instance lock, WAL recovery backup, and close backups.
- Added sequential schema migrations, schema version tracking, and pre-migration user data backup.
- Added versioned release executable output from `build_exe.ps1`.
