# Account skill

## Purpose
Give the analyst and the insights skill **secondary context** about the customer, so a recommendation
does not ignore related information.

## What it returns (`account_json`)
- `primary_account`: the account the analyst is working on.
- `accounts`: every account of the customer (credit card, checking, savings, loans, ...).
- `disputes`: all disputes, including fraud disputes, with type, status and amount.
- `requests`: existing service requests with type and status.

## Rules
- It runs **in parallel** with the transaction skill. Neither depends on the other.
- It is **optional**. If the backend fails, the gateway continues with `{"available": false}` and the
  insights skill says that account context is unavailable.
- Account data is secondary. It must never override facts found in the transactions.
- The primary `account_number` must belong to `customer_id`; otherwise the service returns PERMISSION_DENIED.

## Change history
See `version_history` in skill.json.
