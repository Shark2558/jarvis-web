# tests/test_people_sources.py
"""Profile-URL classification: only known public profile hosts and shapes are ever opened."""

from __future__ import annotations

import pytest

from jarvis.people.sources import classify_profile


@pytest.mark.parametrize(
    ("url", "platform", "canonical"),
    [
        (
            "https://www.linkedin.com/in/satyanadella/?trk=x",
            "linkedin",
            "https://www.linkedin.com/in/satyanadella",
        ),
        (
            "https://in.linkedin.com/in/jane-doe-123",
            "linkedin",
            "https://www.linkedin.com/in/jane-doe-123",
        ),
        ("https://github.com/torvalds", "github", "https://github.com/torvalds"),
        ("https://www.youtube.com/@Google", "youtube", "https://www.youtube.com/@Google"),
        (
            "https://www.youtube.com/channel/UC123abc",
            "youtube",
            "https://www.youtube.com/channel/UC123abc",
        ),
        ("https://x.com/sundarpichai", "x", "https://x.com/sundarpichai"),
        ("https://twitter.com/sundarpichai", "x", "https://x.com/sundarpichai"),
        (
            "https://en.wikipedia.org/wiki/Satya_Nadella",
            "wikipedia",
            "https://en.wikipedia.org/wiki/Satya_Nadella",
        ),
        (
            "https://www.instagram.com/narendramodi/",
            "instagram",
            "https://www.instagram.com/narendramodi",
        ),
        (
            "https://www.facebook.com/narendramodi",
            "facebook",
            "https://www.facebook.com/narendramodi",
        ),
    ],
)
def test_known_profile_shapes_are_classified_and_canonicalised(
    url: str, platform: str, canonical: str
) -> None:
    result = classify_profile(url)

    assert result is not None
    assert (result.platform, result.url) == (platform, canonical)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/torvalds",  # not https
        "https://github.com/",  # no profile
        "https://github.com/torvalds/linux",  # a repo, not a profile
        "https://github.com/orgs/foo",  # reserved
        "https://evil.example.com/in/satya",  # not an allowed host
        "https://linkedin.com.evil.example/in/satya",  # look-alike host
        "https://en.wikipedia.org/wiki/Special:Search",  # namespace page
        "https://www.linkedin.com/jobs/view/1",  # not a profile path
        "javascript:alert(1)",
        "",
        "https://user:pw@github.com/torvalds",  # credentials in URL
    ],
)
def test_other_urls_are_not_profiles(url: str) -> None:
    assert classify_profile(url) is None


def test_non_string_is_not_a_profile() -> None:
    assert classify_profile(None) is None  # type: ignore[arg-type]
