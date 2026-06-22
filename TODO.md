# TODO

- [ ] Implement stable product identity (`product_key`) to make Price History deterministic.
  - [ ] Update DB schema: add `product_key` column to `wishlist` and `price_history` and index it.
  - [ ] Add URL normalization helper in `main.py` to compute `product_key`.
  - [ ] During `/compare` ingestion, store `product_key` in `price_history`.
  - [ ] During `/wishlist/add`, dedupe by `(user_id, product_key)` and store `product_key`.
  - [ ] During `/history`, query by `product_key` and render history consistently.
  - [ ] Update wishlist template links to pass `product_key` instead of raw `product_url`.
- [x] Backfill existing DB rows (best-effort) for `product_key`.

- [ ] Smoke test: add/remove/re-add same product; ensure history remains complete.

- [ ] (Optional) Improve SerpAPI resilience (timeout/retries) and pass error info to templates.


