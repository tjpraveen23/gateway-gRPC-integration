"""Client for the common SQL services: generate -> validate (retry with feedback) -> execute.

Skill backend services (for example the transaction service) consume the common SQL services through this
class, so the retry logic and timing live in one place."""
import json
import time
from dataclasses import dataclass, field

import grpc

from crown.common.v1 import sql_pb2 as pb
from crown.common.v1 import sql_pb2_grpc as pbg

from . import config


class SqlValidationFailed(Exception):
    def __init__(self, errors: list[str], last_sql: str, attempts: int):
        super().__init__(f"SQL validation failed after {attempts} attempts: {errors}")
        self.errors, self.last_sql, self.attempts = errors, last_sql, attempts


@dataclass
class SqlResult:
    sql: str
    rows: list[dict]
    attempts: int
    calls: list[dict] = field(default_factory=list)   # {"call","rpc","start_ms","ms"}, offsets from query start


class SqlQueryClient:
    def __init__(self, generation, validation, execution, max_attempts: int = 3, timeout: float = 30.0):
        self.generation, self.validation, self.execution = generation, validation, execution
        self.max_attempts, self.timeout = max_attempts, timeout

    @classmethod
    def from_addresses(cls, generation_addr: str, validation_addr: str, execution_addr: str, **kw) -> "SqlQueryClient":
        ch = lambda a: grpc.insecure_channel(a)  # noqa: E731  (use mTLS credentials in production)
        return cls(pbg.SqlGenerationServiceStub(ch(generation_addr)), pbg.SqlValidationServiceStub(ch(validation_addr)),
                   pbg.SqlExecutionServiceStub(ch(execution_addr)), **kw)

    @classmethod
    def from_env(cls, **kw) -> "SqlQueryClient":
        return cls.from_addresses(config.service_addr("SQL_GENERATION"), config.service_addr("SQL_VALIDATION"),
                                  config.service_addr("SQL_EXECUTION"), **kw)

    def query(self, question: str, customer_id: str, account_number: str, lookback_days: int,
              correlation_id: str = "") -> SqlResult:
        md = (("x-correlation-id", correlation_id),) if correlation_id else ()
        t0 = time.perf_counter()
        calls: list[dict] = []

        def timed(name, rpc_name, fn, request):
            start = time.perf_counter()
            rec = {"call": name, "rpc": rpc_name, "start_ms": round((start - t0) * 1000), "ms": 0}
            calls.append(rec)
            try:
                return fn(request, timeout=self.timeout, metadata=md)
            finally:
                rec["ms"] = round((time.perf_counter() - start) * 1000)

        feedback, sql, last_sql, errors = "", None, "", []
        for attempt in range(1, self.max_attempts + 1):
            gen = timed("generate_sql", "crown.common.v1.SqlGenerationService/GenerateSql", self.generation.GenerateSql,
                        pb.GenerateSqlRequest(question=question, customer_id=customer_id, account_number=account_number,
                                              lookback_days=lookback_days, feedback=feedback))
            last_sql = gen.sql
            val = timed("validate_sql", "crown.common.v1.SqlValidationService/ValidateSql", self.validation.ValidateSql,
                        pb.ValidateSqlRequest(sql=gen.sql, customer_id=customer_id, account_number=account_number))
            if val.valid:
                sql = val.sanitized_sql
                break
            errors = list(val.errors)
            feedback = f"Previous SQL: {gen.sql}\nValidator errors: {errors}"
        else:
            raise SqlValidationFailed(errors, last_sql, self.max_attempts)

        ex = timed("execute_sql", "crown.common.v1.SqlExecutionService/ExecuteSql", self.execution.ExecuteSql,
                   pb.ExecuteSqlRequest(sql=sql, customer_id=customer_id, account_number=account_number))
        return SqlResult(sql=sql, rows=json.loads(ex.rows_json), attempts=attempt, calls=calls)
