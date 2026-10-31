# Transaction skill

## Purpose
Retrieve the card transactions of **one account only** (the `account_number` sent with the request).
This skill only fetches data. Scenario rules (what is a duplicate, fraud, overdue refund) live in the
**insights** skill. Other accounts and disputes belong to the **account** skill.

## When the gateway should select it
Any credit card issue that needs transaction evidence: duplicate or wrong charges, unrecognised charges,
missing refunds, charges after cancelling a subscription, pending holds, fees and interest.

## Tools it calls (see skill.json `steps`)
1. `Text2SqlService.Text2Sql` writes a scoped SELECT from the profile's data question.
2. `SqlValidatorService.ValidateSql` checks it. If invalid, the errors go back to step 1 (max 3 attempts).
3. `SqlExecutorService.ExecuteSql` runs the sanitized SQL read-only.

## Intent to profile
| Intent | Profile | Window |
|---|---|---|
| duplicate_charge | duplicate_charge | 30 days |
| unauthorized_transaction, unknown_merchant | unauthorized_transaction | 90 days |
| merchant_refund_missing | merchant_refund_missing | 60 days |
| recurring_after_cancellation | recurring_after_cancellation | 120 days |
| incorrect_amount | incorrect_amount | 30 days |
| pending_hold | pending_hold | 14 days |
| fee_or_interest_dispute | fee_or_interest_dispute | 90 days (needs FEE/INTEREST types) |
| anything else | general_transaction_inquiry | 30 days |

## Data semantics
- `amount` is always positive. Refunds have `txn_type = REFUND`.
- `status`: POSTED, PENDING or REVERSED. A PENDING row that shares `auth_code` with a POSTED row is the same authorisation.
- `txn_ts` is UTC.

## Output
`transactions_json`, `row_count`, `sql` (audit), `profile`. If nothing is found the gateway routes to manual review.

## Change history
See `version_history` in skill.json. Add an entry and bump `version` on every change.
