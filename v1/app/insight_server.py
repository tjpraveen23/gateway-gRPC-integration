"""gRPC: InsightService (the insights skill's tool)."""
import json
import logging
from concurrent import futures

import grpc

import crown_pb2 as pb
import crown_pb2_grpc as pbg
from common import INSIGHT_ADDR, chat_json, port_of

log = logging.getLogger("insight")

SYSTEM = """You are the Insight Agent for a credit card contact center. You help an analyst by analysing
the transactions of ONE account and recommending actions strictly according to the SOP excerpts.
You are given an INSIGHT SKILL document: apply its general rules and the section that matches the given intent.
Rules:
- Facts come only from TRANSACTIONS (primary account). ACCOUNT REFERENCE is secondary context
  (other accounts, existing disputes, open requests). Use it to add context or avoid duplicate work,
  never to change the facts about the transactions. If it says available=false, mention that briefly.
- Use ONLY the supplied data and SOP excerpts. Never invent transactions, amounts or policy.
- Every recommendation must cite an SOP section id that appears in the excerpts.
- If the SOP excerpts do not cover the situation, set classification to "needs_manual_review".
- You never execute actions; you only advise the analyst.
Return a single JSON object with exactly these keys:
  classification (string), confidence (number 0-1),
  evidence (array of {"txn_id": string, "reason": string}),
  recommended_actions (array of short strings),
  analyst_action_message (string, imperative, concise, mentions amounts and SOP ids),
  customer_script (string, 2-3 sentences the analyst can say),
  sop_references (array of SOP section ids),
  account_context (string, one sentence on relevant secondary account information, or "")."""


class Insight(pbg.InsightServiceServicer):
    def Analyze(self, request, context):
        sop_text = "\n\n".join(
            f"[{c.section_id}] {c.title} (version {c.doc_version})\n{c.text}" for c in request.sop_chunks)
        user = (f"INSIGHT SKILL:\n{request.insight_skill}\n\n"
                f"INTENT: {request.intent}\nGOAL: {request.goal}\n\n"
                f"CUSTOMER MESSAGE:\n{request.customer_message}\n\n"
                f"EXTRACTED ENTITIES (JSON):\n{request.entities_json}\n\n"
                f"TRANSACTIONS (JSON, primary account):\n{request.transactions_json}\n\n"
                f"ACCOUNT REFERENCE (JSON, secondary):\n{request.account_json}\n\n"
                f"SOP EXCERPTS:\n{sop_text}\n\nRespond in JSON.")
        try:
            out = chat_json(SYSTEM, user)
        except Exception as e:  # noqa: BLE001
            log.exception("insight failed")
            context.abort(grpc.StatusCode.INTERNAL, f"LLM error: {e}")
        allowed = {c.section_id for c in request.sop_chunks}  # guardrail: only retrieved sections
        out["sop_references"] = [s for s in out.get("sop_references", []) if s in allowed]
        return pb.AnalyzeResponse(result_json=json.dumps(out))


def serve(addr: str = INSIGHT_ADDR):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pbg.add_InsightServiceServicer_to_server(Insight(), server)
    server.add_insecure_port(f"[::]:{port_of(addr)}")
    server.start()
    log.info("InsightService listening on %s", addr)
    return server


if __name__ == "__main__":
    serve().wait_for_termination()
