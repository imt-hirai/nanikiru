# 麻雀 何切る 200問 - 起動/停止用 Makefile
#   make start    : サーバーをバックグラウンドで起動
#   make stop     : サーバーを停止
#   make restart  : 再起動
#   make status   : 起動状態の確認
#   make open     : ブラウザで開く（macOS）
#   make generate : 問題(web/problems.js)を再生成
#   make logs     : サーバーログを表示
#   PORT を変えるとき: make start PORT=9000

PORT    ?= 8081
HOST    ?= 127.0.0.1
PYTHON  ?= python3
WEB_DIR := web
RUN_DIR := .run
PID_FILE := $(RUN_DIR)/server.pid
LOG_FILE := $(RUN_DIR)/server.log
URL     := http://localhost:$(PORT)/
# PIDファイルが無くても、このアプリのサーバーだけをポートから特定する
FIND_PID = for p in $$(lsof -t -nP -iTCP:$(PORT) -sTCP:LISTEN 2>/dev/null); do ps -p $$p -o command= | grep -q "http.server $(PORT).*--directory $(WEB_DIR)" && echo $$p; done

.PHONY: help start stop restart status open generate logs

help:
	@echo "使い方:"
	@echo "  make start    サーバー起動 ($(URL))"
	@echo "  make stop     サーバー停止"
	@echo "  make restart  再起動"
	@echo "  make status   起動状態を確認"
	@echo "  make open     ブラウザで開く"
	@echo "  make generate 問題を再生成"
	@echo "  make logs     ログ表示"

start:
	@mkdir -p $(RUN_DIR)
	@if [ -f $(PID_FILE) ] && kill -0 `cat $(PID_FILE)` 2>/dev/null; then \
		echo "既に起動しています (PID `cat $(PID_FILE)`): $(URL)"; \
	else \
		if lsof -nP -iTCP:$(PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
			echo "ポート $(PORT) は使用中です。make start PORT=<別のポート> を指定してください。"; exit 1; \
		fi; \
		nohup $(PYTHON) -m http.server $(PORT) --bind $(HOST) --directory $(WEB_DIR) >$(LOG_FILE) 2>&1 & echo $$! >$(PID_FILE); \
		sleep 1; \
		if kill -0 `cat $(PID_FILE)` 2>/dev/null; then \
			echo "起動しました (PID `cat $(PID_FILE)`): $(URL)"; \
		else \
			echo "起動に失敗しました。ログ: $(LOG_FILE)"; rm -f $(PID_FILE); exit 1; \
		fi; \
	fi

stop:
	@if [ -f $(PID_FILE) ] && kill -0 `cat $(PID_FILE)` 2>/dev/null; then \
		kill `cat $(PID_FILE)` && rm -f $(PID_FILE) && echo "停止しました"; \
	else \
		rm -f $(PID_FILE); \
		PID=$$($(FIND_PID)); \
		if [ -n "$$PID" ]; then \
			kill $$PID && echo "停止しました (PID $$PID / PIDファイルなし・ポート $(PORT) から検出)"; \
		else \
			echo "起動していません"; \
		fi; \
	fi

restart: stop start

status:
	@if [ -f $(PID_FILE) ] && kill -0 `cat $(PID_FILE)` 2>/dev/null; then \
		echo "起動中 (PID `cat $(PID_FILE)`): $(URL)"; \
	elif [ -n "$$($(FIND_PID))" ]; then \
		echo "起動中 (PID $$($(FIND_PID))・PIDファイルなし): $(URL)"; \
	else \
		echo "停止中"; \
	fi

open:
	@open $(URL)

generate:
	$(PYTHON) tools/generate.py

logs:
	@tail -n 50 $(LOG_FILE) 2>/dev/null || echo "ログはまだありません"
