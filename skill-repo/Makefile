.PHONY: proto lint test run
proto:        ## generate python stubs for every skill (imports common protos from core-gateway)
	python scripts/gen_proto.py
lint:         ## validate skill folders + skill.json against the gateway registry (uses core-gateway)
	. ./scripts/env.sh && cd $$CORE_GATEWAY && . ./tools/env.sh && SKILLS_DIR=$(CURDIR)/skills python tools/lint_skills.py
test:
	. ./scripts/env.sh && python -m pytest -q
run:          ## the three skill services (start core-gateway first)
	./scripts/run_skills.sh
