# Software Delivery pack

## Markdown test-case export

Tool: `software_delivery.export_test_cases_markdown`

Exports structured test cases and their source citations as Markdown. The output contains generated cases and citations only — no objectives, strategy, coverage summaries, scope, or entry/exit criteria.

### Input

Same shape as the JSON output from `software_delivery.generate_test_cases`:

```json
{
  "output_style": "steps",
  "test_cases": [{
    "title": "...",
    "steps": ["..."],
    "expected": "...",
    "references": [{"source_id": "...", "source_type": "..."}]
  }]
}
```

### Output template

```markdown
# Test Cases

**Output style:** {output_style}

## {n}. {title}

### Steps

{numbered list when output_style is steps | bullet list when gherkin}

### Expected result

{expected}

### References

- `{source_id}` ({source_type})
```

### Formatting rules

- One root `output_style` per export (`steps` or `gherkin`)
- Case order preserved from input
- References sorted by `(source_type, source_id)` as normalized by `GeneratedTestCase`
- Single trailing newline at EOF
- Heading levels: `#` document, `##` case, `###` section

### Validation

Invalid or empty input raises `MarkdownExportValidationError` before any Markdown is produced.
