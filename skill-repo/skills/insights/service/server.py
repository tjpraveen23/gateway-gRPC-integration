"""Insights skill backend service (gRPC)."""
from bank.insight.v1 import insight_pb2_grpc as pbg
from crown_common import config
from crown_common.grpc_server import run_forever, start_server
from skills.insights.service.handlers.analyze import AnalyzeHandler


class InsightServicer(pbg.InsightServiceServicer):
    def __init__(self, handler: AnalyzeHandler):
        self.handler = handler

    def Analyze(self, request, context):
        return self.handler.handle(request, context)


def serve(addr: str | None = None):
    handler = AnalyzeHandler()
    return start_server(lambda s: pbg.add_InsightServiceServicer_to_server(InsightServicer(handler), s),
                        addr or config.service_addr("INSIGHT"))


if __name__ == "__main__":
    run_forever(serve, "InsightService")
