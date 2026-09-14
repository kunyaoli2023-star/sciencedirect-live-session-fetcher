# Public-release checklist

Use this checklist before pushing the skill or downloader to GitHub.

## Include

- `SKILL.md`, UI metadata, browser launchers, fetchers, validation logic, and
  concise documentation;
- a small synthetic or openly licensed example CSV;
- a code license and a notice that publisher terms still apply;
- instructions that each user must authenticate with their own lawful access.

## Exclude

- publisher PDFs and ZIP archives containing them;
- Cookies, browser user-data directories, credential files, signed PDF URLs,
  and screenshots containing private account data;
- absolute local paths, private institution names, and raw logs with session
  identifiers;
- claims that the tool creates or shares subscription access.

## Usability requirements

- Accept paths, ports, waits, and input files as arguments.
- Provide a one-row test before full-batch execution.
- Document resume, low-frequency pacing, status values, and retry behavior.
- Keep credential entry and CAPTCHA handling manual and visible.
- Provide a dry-run or metadata-only mode when the project needs repeated
  public use.
