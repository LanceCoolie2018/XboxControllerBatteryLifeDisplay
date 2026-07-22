# Microsoft Partner Center — developer account & getting paid ($5 BatteryHUD)

You need a **Microsoft Partner Center** developer account to list BatteryHUD on the Microsoft Store and receive the **$4.99 / $5** payments.

## 1. Create a developer account

1. Go to [Partner Center](https://partner.microsoft.com/dashboard) and sign in with the Microsoft account you want tied to the app (or create one).
2. Open **Account settings** → enroll as an **individual** or **company** developer.
3. Pay the **one-time registration fee** (Microsoft sets this; often ~$19 USD for individuals — confirm on the enrollment page).
4. Complete identity verification if prompted (government ID / business docs for companies).

## 2. Set up payouts (how you receive money)

1. In Partner Center: **Account settings** → **Payout and tax**.
2. **Payout account**
   - Add a bank account that can receive electronic deposits in your country.
   - Currency/market depends on where Microsoft supports payouts for your region.
3. **Tax profile**
   - Complete the tax interview (W-9 for US persons, W-8BEN / equivalent for non-US, etc.).
   - Without a valid tax profile, **payouts are held**.
4. Save and wait for status **Active** / verified.

Microsoft deposits **your share of Store sales** on their payout schedule (typically monthly after thresholds). You do **not** need a custom payment system in BatteryHUD — the Store handles the $5 charge.

## 3. Create the app listing

1. Partner Center → **Apps and games** → **New product** → **MSIX or PWA app**.
2. Reserve name: **BatteryHUD**.
3. Pricing: set to **$4.99** (or $5.00 if offered) for the markets you enable.
4. Fill:
   - Description, screenshots (see `store/` assets when ready)
   - Age rating questionnaire
   - **Privacy policy URL** (required) → use published `docs/privacy.md` / GitHub Pages
   - Support contact (can point at GitHub Issues)
5. Upload the **MSIX** package built from `master` (see `scripts/build-msix.ps1`).
6. Submit for **certification**. After pass, set visibility to public.

## 4. Package flights (test like a real customer)

Before public $5 launch:

1. Create a **package flight** (internal / private audience) if available on your account.
2. Install **from the Store** on this laptop with that flight.
3. Use **Bug** → file a test Issue → confirm Pi monkey queues AssIsstant work.

Sideload is fine for packaging smoke tests; **Store install** is the real customer simulation.

## 5. After each paid update

1. Merge AssIsstant → master (you verified).
2. Bump version (must increase for every Store submission).
3. Build new MSIX → upload → certification → publish.
4. Close or comment related GitHub Issues when the fix is live.

## Links

- Partner Center: https://partner.microsoft.com/dashboard  
- Payout help: search Partner Center docs for “payout account” and “tax profile”  
- App submissions: Partner Center → your app → **Packages** / **Submissions**
