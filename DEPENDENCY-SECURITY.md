# Dependency security

Use the constraints alongside the existing project requirements when applying compatible networking-library security fixes:

```sh
python -m pip install --upgrade aiohttp multidict -c security-constraints.txt
python -m pip check
```

Verify imports and startup as the service account, retain a complete rollback environment, and check the archive's normal event processing after restart. These files contain reusable version constraints only; private deployment paths, credentials and runtime data are intentionally excluded.
