# tests/fixtures/book/repo/tests/fake_keys.py -- build book generator fixture (not imported)
"""A FAKE secret-shaped string: the snapshot's secret scan must refuse it unless its SHA-256 is
listed in gen/fake_secrets.txt (docs/plans/r6-build-book.md D5). It is not a real key."""

FAKE_MAPS_KEY = "AIzaSyFAKE-not-a-real-key-0000000000000"
