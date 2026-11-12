"""Research a picture, never a person (R11.1 Part D; docs/plans/r11-1-observations.md D17, D21-D;
Layer 4 vision input, Layer 5 Research & Intel).

    eyes       the ONE model call: the first look at a picture, by a brain that sees and never
               trains on it; admitted and metered; strict JSON asked for
    guard      plain code, no model: what may be said and searched from that answer (a thing, never
               a person; a name only from the picture's own words, and then only as an offer)
    scene      the description screens (every picture; again for a picture with a person)
    words      the word lists and shapes the guards decide with
    turnguard  the main brain's path: on a turn that carried a picture, a person's name only
               when the owner typed it (else an offer from the picture's text, or no); a web
               query with no name he did not type or the picture does not show
    search     the web search for the things, under the owner's "Search the web" row and every cap
    research   PictureResearch: the flow and the fixed-template reply
    tools      picture_research through the gateway (row "Pictures", R1)
    part       the join with the app (jarvis.fixes.ports)

The owner asked for the public-figure check to be removed so that JARVIS would say who is in a
picture. That was declined: `jarvis.people.gate` is untouched and nothing here matches a face to
a name. Import the pieces from their modules.
"""
