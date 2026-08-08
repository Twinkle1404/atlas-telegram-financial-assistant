.PHONY: install install-dev run test chat

install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements.txt -r requirements-dev.txt

run:
	python run.py

test:
	pytest

chat:
	python scripts/chat_cli.py
