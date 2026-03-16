# Praxis CI Integration

## GitHub Actions

Copy `github-actions.yml` to `.github/workflows/praxis.yml` in your repo.

This workflow:
1. Runs on every push and PR
2. Installs Praxis
3. Verifies all specs in `specs/` directory
4. Saves JSON results as a build artifact
5. Shows human-readable output in the build log

## Customization

- Change `specs/` to match your spec file location
- Add `--timeout 60` for complex specs
- Use `--format json` output in downstream steps for agent integration
