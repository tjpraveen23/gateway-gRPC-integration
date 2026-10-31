.PHONY: proto registry seed lint test run
proto:        ## generate common python code + registry/descriptors.pb (common + skill-repo protos)
	python tools/gen_proto.py
registry:     ## rebuild only registry/descriptors.pb (after a skill-repo proto change)
	python tools/gen_proto.py --registry
seed:         ## demo database (data/bank.db)
	. ./tools/env.sh && python -c "from crown_common.testing.demo_data import seed; seed()"
lint:         ## validate the skill-repo contracts against the registry (needs ../skill-repo or SKILL_REPO)
	. ./tools/env.sh && python tools/lint_skills.py
test:
	. ./tools/env.sh && python -m pytest -q
run:          ## common services + gateway on :8000
	./tools/run_all.sh
