# TODO

- [ ] Update `main.py`: make SerpAPI requests more resilient (longer timeout + retries with backoff) and capture error message.
- [ ] Update `main.py` + `compare_products`: pass SerpAPI error info to templates.
- [x] Update `templates/results.html`: show SerpAPI error message when present.
- [ ] Smoke test: run the server and verify `/compare` behavior under failure and success.


