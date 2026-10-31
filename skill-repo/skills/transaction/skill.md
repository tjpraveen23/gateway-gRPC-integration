# Transaction skill

## Purpose
Retrieve the card transactions of **one account only** (the `account_number` sent with the request).
This skill only fetches data. Scenario rules (what is a duplicate, fraud, overdue refund) live in the
**insights** skill. Other accounts and disputes belong to the **account** skill.

## Backend service
`bank.transaction.v1.TransactionService/GetTransactions` (folder `service/`). The service owns the data profiles
(`service/config/profiles.json`: window and data question per intent) and consumes the **common** services:
`SqlGenerationService`, `SqlValidationService`, `SqlExecutionService` (folder `common/services/`).
If the validator rejects the SQL, the service retries generation with the validator errors (max 3 attempts), then
fails with FAILED_PRECONDITION, which the gateway turns into manual review.

## When the gateway should select it
Any credit card issue that needs transaction evidence: duplicate or wrong charges, unrecognised charges,
missing refunds, charges after cancelling a subscription, pending holds, fees and interest.

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
`transactions_json`, `row_count`, `sql` (audit), `profile`. The response also lists the service's own downstream calls
(`downstream_calls`) so the gateway timeline shows SQL generation, validation and execution times. If nothing is found
the gateway routes to manual review.

## Change history
See `version_history` in skill.json. Add an entry and bump `version` on every change.
