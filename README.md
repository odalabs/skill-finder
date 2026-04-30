# skill-finder

> By [ODA Labs](https://odalabs.ru)

Claude Code skill, который ищет другие Claude Code skills на GitHub под нужное действие и ранжирует их по релевантности, звёздам, свежести и доверию к источнику.

## Что делает

Пользователь говорит «найди скил для X» → Claude вытаскивает английские ключевые слова, гонит GitHub Code Search по `filename:SKILL.md`, парсит frontmatter каждого хита, считает score и возвращает топ-5 с готовой install-командой.

Скоринг (composite, max 100):

- **50%** — match query ↔ `name`+`description` из frontmatter
- **20%** — звёзды parent-репы (log10)
- **15%** — recency (≤1 года = full score)
- **15%** — source-bonus (`anthropics/*` → +15, `awesome` / `claude-skill` в имени репы → +7)

## Установка

```bash
git clone https://github.com/odalabs/skill-finder ~/.claude/skills/skill-finder
```

Перезапусти Claude Code — скил подхватится автоматически (увидишь в available-skills как `skill-finder`).

## Требования

1. **Python 3.8+**
2. **GitHub CLI с авторизацией:**
   ```bash
   # Windows
   winget install GitHub.cli
   # macOS
   brew install gh

   gh auth login   # web-flow, минимально нужен scope `public_repo`
   ```

   Без `gh auth` (или `$GITHUB_TOKEN` в env) Code Search не работает — REST API требует токен.

## Как пользоваться

После установки просто говори в Claude Code:

- «найди скил для редактирования docx»
- «есть готовый скил под slack-уведомления»
- «/skill-finder mermaid diagram»
- «какой скил поставить чтобы парсить PDF»

Claude сам подхватит триггер, переведёт твой запрос в английские ключи (если нужно) и прогонит поиск. Установку без явного «да» делать не будет — это сторонний код.

## Прямой запуск скрипта

```bash
python ~/.claude/skills/skill-finder/scripts/search.py "copywriting sales ad" --limit 5
python ~/.claude/skills/skill-finder/scripts/search.py "pdf extract" --json
python ~/.claude/skills/skill-finder/scripts/search.py "slack" --debug
```

Опции:
- `--limit N` — сколько вернуть (default 5)
- `--json` — машинно-читаемый формат
- `--debug` — verbose-лог в stderr

## Известные ограничения v1

1. Только Code Search — отдельные awesome-листы пока не парсятся.
2. Code Search индексирует только default branch и файлы ≤384 KB (для скилов норм).
3. Дедупликация форков пока не сделана.
4. Match чисто по словам, без эмбеддингов — для русских запросов модель должна перевести заранее.

## Структура

```
skill-finder/
├── SKILL.md          ← триггер-фразы и workflow для модели
├── README.md         ← этот файл
├── LICENSE           ← MIT
└── scripts/
    └── search.py     ← логика поиска и ранжирования
```

## Лицензия

MIT — делайте что хотите, форкайте, улучшайте.
