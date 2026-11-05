# pSSID Credential Manager - developer & operator entry points
.DEFAULT_GOAL := help
SHELL := /bin/bash

.PHONY: help install build dev test test-install smoke backup restore up down logs clean genkey

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install all workspace dependencies
	npm install

build: ## Build server + client
	npm run build

dev: ## Run server and client dev servers (two terminals recommended)
	@echo "Run 'make dev-server' and 'make dev-client' in separate terminals"

dev-server: ## Run the API server in watch mode
	npm run dev:server

dev-client: ## Run the Vite client dev server
	npm run dev:client

test: ## Run the mandatory Vitest suites (crypto, derivation, authz, template)
	npm test

test-install: ## Exercise install.sh against stub docker/curl (no daemon needed)
	bash scripts/test-install.sh

smoke: ## Walk the full user journey against a running stack
	bash scripts/smoke.sh

backup: ## Dump the database (refuses to write an empty archive)
	bash scripts/backup.sh ./backups

restore: ## Restore from an archive: make restore ARCHIVE=./backups/<file>.gz
	bash scripts/restore.sh $(ARCHIVE)

genkey: ## Generate a fresh 256-bit master KEK (prints to stdout)
	@node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"

up: ## Start the Docker Compose stack
	docker compose up -d --build

down: ## Stop the Docker Compose stack
	docker compose down

logs: ## Tail app logs
	docker compose logs -f app

clean: ## Remove build artifacts and node_modules
	rm -rf services/*/dist services/*/node_modules node_modules coverage
