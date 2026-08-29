# HITL Chatbot — lệnh tắt.  (Windows: dùng "python -m" trực tiếp nếu không có make)

.PHONY: install test sim report serve cli clean

install:
	pip install -r requirements.txt

test:
	pytest -q

sim:
	python scripts/run_simulation.py --seed 42

report: sim
	python scripts/generate_report.py

serve:
	uvicorn app:app --reload

cli:
	python reviewer_cli.py list

clean:
	rm -f data/state/*.json
