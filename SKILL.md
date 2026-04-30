---
name: skill-finder
description: Use this skill when the user asks to find or discover a Claude Code skill on GitHub for a specific task — phrases like «найди скил для X», «есть готовый скил под Y», «/skill-finder Z», «какой скил поставить чтобы…», «где взять скил для…», «search claude skill for…», «is there a skill that…». Searches public GitHub for SKILL.md files, ranks by description-match + stars + recency + source-trust, returns top 5 with install commands. Trigger whenever the user wants to discover/install a third-party skill rather than write one from scratch. Do NOT trigger when the user wants to *create* a new skill (that is skill-creator) or asks about already-installed skills.
allowed-tools: [Read, Bash, Glob, Grep]
---

# skill-finder — поиск Claude Code скилов на GitHub

Цель: по описанию задачи пользователя найти готовый сторонний скил на GitHub, отранжировать кандидатов и показать топ-5 с командой установки.

## Когда триггерить

- «**найди скил для рендера mermaid**»
- «**есть готовый скил под парсинг ИНН**»
- «**/skill-finder slack**» / «**/skill-finder docx редактирование**»
- «**какой скил поставить чтобы делать X**»
- «**где взять claude skill для Y**»
- «search a skill for Z», «is there a claude skill that…»

**Не** триггерить на:
- Просьбу **создать новый** скил → это `skill-creator`.
- Вопросы про уже установленные скилы (`ls ~/.claude/skills/` хватит).
- Поиск обычных GitHub-репозиториев / библиотек / MCP-серверов (это другое).

## Процесс

### 1. Извлечь поисковые ключи

Пользовательский запрос обычно на русском и описательный («хочу скил который умеет красиво форматировать markdown-таблицы»). GitHub Code Search ищет по содержимому файлов, а 99% SKILL.md написаны по-английски. Поэтому:

1. Из запроса вытащи 2-4 английских ключевых слова, описывающих **действие или объект** (не «хочу», «помоги», «скил»).
2. Если запрос содержит точное название технологии/формата (`docx`, `mermaid`, `slack`, `pdf`) — это сильный сигнал, оставляй как есть.
3. Если запрос про русскоязычную нишу без англо-аналога (например «складчики», «ИНН/ОГРН») — делай **два прогона**: с RU-словами и с EN-аналогами.

**Примеры:**
- «найди скил для генерации презентаций» → `pptx slides presentation`
- «нужен скил под рендер диаграмм» → `mermaid diagram render`
- «скил для парсинга ИНН» → прогон 1: `inn ogrn russian company`, прогон 2: `ИНН ОГРН`
- «slack-уведомления» → `slack notification message`

### 2. Запустить поиск

```bash
python ~/.claude/skills/skill-finder/scripts/search.py "<keywords>" --limit 5
```

Скрипт сам:
- берёт токен через `gh auth token` (fallback: `$GITHUB_TOKEN` / `$GH_TOKEN`),
- делает GitHub Code Search по `filename:SKILL.md <keywords>`,
- стягивает frontmatter (`name`, `description`) каждого SKILL.md,
- получает метаданные репы (stars, last push),
- считает score: 50% match (query ↔ name+description) + 20% stars (log) + 15% recency (≤1 года = full) + 15% source-trust (anthropics/* → +15, awesome/claude-skill в имени репы → +7),
- печатает Markdown с топ-N.

Опции:
- `--limit N` — сколько вернуть (default 5)
- `--json` — машинно-читаемый формат

### 3. Презентовать результат

Скрипт уже отдаёт готовый Markdown-блок — проксируй его пользователю **как есть**, плюс добавь от себя 1-2 строки контекста:
- какой запрос был отправлен (особенно если ты переводил с русского — это важно, иначе пользователь не поймёт почему такой результат);
- на что обратить внимание (явно подходящий vs near-miss).

Если результатов **0** — скажи это явно, попробуй переформулировать с другими EN-ключами и запусти ещё раз. Не выдумывай скилы.

Если результатов **много и они шумные** (top score < 25) — это сигнал «реальной находки нет, есть только похожие». Скажи об этом.

### 4. Предложить установку

Каждая запись содержит готовую команду установки в `~/.claude/skills/<name>/`. Спроси у пользователя что ставить — **никогда не клонируй сам без явного подтверждения**, это сторонний код.

После клонирования:
- `cat ~/.claude/skills/<name>/SKILL.md | head -40` — пусть пользователь увидит что внутри,
- предупреди что скил нужно перезагрузить (новая сессия Claude Code или `/skills reload`, в зависимости от версии).

## Edge cases

- **Code Search 403 / rate-limit** — у Code Search лимит 30 req/min. Скрипт делает 1 search + N raw fetch + N repo-meta. При `--limit 5` это ~11 запросов, влезает. Если поймал 403 — подождать минуту и повторить.
- **Нет токена вообще** — скрипт упадёт с предупреждением. Проверь `gh auth status`. Без auth Code Search не работает.
- **SKILL.md без frontmatter** — скрипт пропускает такие хиты (это шум: README-шаблоны, документация про скилы и т.п.).
- **Запрос только из стоп-слов** («скил», «нужен», «хочу») — отказывайся искать, переспроси у пользователя что конкретно нужно делать.
- **Anthropic-skills** (репа `anthropics/skills`) даёт +15 source-bonus и почти всегда всплывает в топе для общих запросов (pdf, docx, xlsx, pptx) — это правильно.

## Что вернуть пользователю в конце

Шаблон ответа:

```
Искал по запросу: «<EN ключи>»

<вывод скрипта>

Самый подходящий — №<N> (<name>). Поставить?
```

Не пересказывай описания скилов своими словами — пользователю важна **оригинальная формулировка** из frontmatter, по которой Claude триггерит скил у себя.
