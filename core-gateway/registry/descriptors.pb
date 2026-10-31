
Ý
#crown/common/v1/sop_retrieval.protocrown.common.v1"U
RetrieveSopRequest
query (	Rquery
top_k (RtopK
topic (	Rtopic"Š
SopChunk

section_id (	R	sectionId
title (	Rtitle
text (	Rtext
score (Rscore
doc_version (	R
docVersion"H
RetrieveSopResponse1
chunks (2.crown.common.v1.SopChunkRchunks2o
SopRetrievalServiceX
RetrieveSop#.crown.common.v1.RetrieveSopRequest$.crown.common.v1.RetrieveSopResponsebproto3
„
crown/common/v1/sql.protocrown.common.v1"¹
GenerateSqlRequest
question (	Rquestion
customer_id (	R
customerId%
account_number (	RaccountNumber#
lookback_days (RlookbackDays
feedback (	Rfeedback"'
GenerateSqlResponse
sql (	Rsql"n
ValidateSqlRequest
sql (	Rsql
customer_id (	R
customerId%
account_number (	RaccountNumber"h
ValidateSqlResponse
valid (Rvalid#
sanitized_sql (	RsanitizedSql
errors (	Rerrors"m
ExecuteSqlRequest
sql (	Rsql
customer_id (	R
customerId%
account_number (	RaccountNumber"N
ExecuteSqlResponse
	rows_json (	RrowsJson
	row_count (RrowCount2p
SqlGenerationServiceX
GenerateSql#.crown.common.v1.GenerateSqlRequest$.crown.common.v1.GenerateSqlResponse2p
SqlValidationServiceX
ValidateSql#.crown.common.v1.ValidateSqlRequest$.crown.common.v1.ValidateSqlResponse2l
SqlExecutionServiceU

ExecuteSql".crown.common.v1.ExecuteSqlRequest#.crown.common.v1.ExecuteSqlResponsebproto3
–
crown/common/v1/timing.protocrown.common.v1"]

CallTiming
call (	Rcall
rpc (	Rrpc
start_ms (RstartMs
ms (Rmsbproto3
ƒ
bank/account/v1/account.protobank.account.v1"ƒ
GetCustomerAccountsRequest
customer_id (	R
customerId%
account_number (	RaccountNumber

info_types (	R	infoTypes">
GetCustomerAccountsResponse
result_json (	R
resultJson2‚
AccountServicep
GetCustomerAccounts+.bank.account.v1.GetCustomerAccountsRequest,.bank.account.v1.GetCustomerAccountsResponsebproto3
¯
bank/insight/v1/insight.protobank.insight.v1#crown/common/v1/sop_retrieval.proto"»
AnalyzeRequest#
insight_skill (	RinsightSkill)
customer_message (	RcustomerMessage
intent (	Rintent
goal (	Rgoal+
transactions_json (	RtransactionsJson!
account_json (	RaccountJson8

sop_chunks (2.crown.common.v1.SopChunkR	sopChunks#
entities_json (	RentitiesJson"2
AnalyzeResponse
result_json (	R
resultJson2^
InsightServiceL
Analyze.bank.insight.v1.AnalyzeRequest .bank.insight.v1.AnalyzeResponsebproto3
¾
%bank/transaction/v1/transaction.protobank.transaction.v1crown/common/v1/timing.proto"¹
GetTransactionsRequest
customer_id (	R
customerId%
account_number (	RaccountNumber
intent (	Rintent
question (	Rquestion#
entities_json (	RentitiesJson"˜
GetTransactionsResponse+
transactions_json (	RtransactionsJson
	row_count (RrowCount
sql (	Rsql
profile (	Rprofile#
lookback_days (RlookbackDays
attempts (RattemptsF
downstream_calls (2.crown.common.v1.CallTimingRdownstreamCalls2‚
TransactionServicel
GetTransactions+.bank.transaction.v1.GetTransactionsRequest,.bank.transaction.v1.GetTransactionsResponsebproto3